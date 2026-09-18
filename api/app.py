"""HTTP API over agent.ask().

  GET  /health        liveness: the process is up. No database, no LLM.
                      This is what the load balancer polls.
  GET  /health/ready  readiness: database reachable, pgvector present,
                      courses and embedded policy chunks loaded.
  POST /api/ask       {"question": "..."}  ->  answer, citations, context

Dev:   flask --app api.app run --debug          (docker compose does this)
Prod:  gunicorn -c api/gunicorn_conf.py api.app:app
"""

import logging
import os
import time
import uuid

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

from agent.graph import ask, pipeline_version
from api.serialize import to_response
from core.db import connection, pool_stats

MAX_QUESTION_CHARS = 500
MAX_BODY_BYTES = 16 * 1024

log = logging.getLogger("api")


class InvalidQuestion(ValueError):
    pass


def parse_question(payload) -> str:
    """Validate the request body. Returns the question, stripped."""
    if not isinstance(payload, dict):
        raise InvalidQuestion("Body must be a JSON object like {\"question\": \"...\"}.")
    question = payload.get("question")
    if not isinstance(question, str):
        raise InvalidQuestion("'question' must be a string.")
    question = question.strip()
    if not question:
        raise InvalidQuestion("'question' is empty.")
    if len(question) > MAX_QUESTION_CHARS:
        raise InvalidQuestion(f"Keep questions under {MAX_QUESTION_CHARS} characters.")
    return question


def error(status: int, code: str, message: str):
    return jsonify(error={"code": code, "message": message,
                          "request_id": g.get("request_id")}), status


def _setup_cors(app: Flask) -> None:
    """Cross-origin access only for origins listed in CORS_ORIGINS.

    In production the UI and API share an origin behind the load balancer,
    so this stays unset. It exists for a dev server on another port.
    """
    origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    if origins:
        from flask_cors import CORS
        CORS(app, resources={r"/api/*": {"origins": origins}})


def create_app(ask_fn=ask) -> Flask:
    """ask_fn is injectable so tests can run without a database or an API key."""
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES
    app.json.sort_keys = False  # type: ignore[attr-defined]
    _setup_cors(app)
    version = pipeline_version()

    @app.before_request
    def start_timer():
        g.request_id = uuid.uuid4().hex[:12]
        g.started = time.monotonic()

    @app.after_request
    def stamp(resp):
        resp.headers["X-Request-Id"] = g.get("request_id", "")
        if request.path != "/health":      # the load balancer polls this constantly
            ms = (time.monotonic() - g.get("started", time.monotonic())) * 1000
            log.info("request_id=%s %s %s -> %s %.0fms", g.get("request_id"),
                     request.method, request.path, resp.status_code, ms)
        return resp

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/health/ready")
    def ready():
        try:
            with connection() as conn:
                ext = conn.execute(
                    "SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
                courses = conn.execute("SELECT count(*) AS n FROM courses").fetchone()["n"]
                chunks = conn.execute(
                    "SELECT count(*) AS n FROM policy_chunks WHERE embedding IS NOT NULL"
                ).fetchone()["n"]
        except Exception:
            log.exception("request_id=%s readiness check failed", g.request_id)
            return error(503, "db_unavailable", "Database unreachable.")
        ok = ext is not None and courses > 0 and chunks > 0
        return jsonify(
            status="ok" if ok else "not_loaded",
            pgvector=ext["extversion"] if ext else None,
            courses=courses,
            policy_chunks=chunks,
            pipeline=version,
            pool=pool_stats(),
        ), (200 if ok else 503)

    @app.post("/api/ask")
    def ask_endpoint():
        if not request.is_json:
            return error(415, "unsupported_media_type",
                         "Send JSON with Content-Type: application/json.")
        try:
            question = parse_question(request.get_json(silent=True))
        except InvalidQuestion as exc:
            return error(400, "invalid_question", str(exc))

        try:
            state = ask_fn(question)
        except Exception:
            # The graph catches model errors itself; anything reaching here
            # is infrastructure (database, pool exhausted, a bug). Log the
            # details, send nothing internal to the client.
            log.exception("request_id=%s ask failed", g.request_id)
            return error(503, "unavailable",
                         "Something went wrong answering that. Try again in a moment.")

        body = to_response(state)
        body["request_id"] = g.request_id
        body["pipeline"] = version
        return jsonify(body)

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        # 404, 405, 413 ... as JSON instead of Werkzeug's HTML pages.
        code = (exc.name or "error").lower().replace(" ", "_")
        return error(exc.code or 500, code, exc.description or "")

    return app


app = create_app()
