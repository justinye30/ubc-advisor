import os

import psycopg
from flask import Flask, jsonify

app = Flask(__name__)
DATABASE_URL = os.environ["DATABASE_URL"]


@app.get("/health")
def health():
    """Liveness probe: confirms DB connectivity and pgvector availability."""
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
                )
                row = cur.fetchone()
                cur.execute("SELECT count(*) FROM _scaffold_check")
                count = cur.fetchone()[0]
        return jsonify(
            status="ok",
            pgvector=row[0] if row else None,
            scaffold_rows=count,
            note="hello",
        )
    except Exception as exc:
        return jsonify(status="error", detail=str(exc)), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
