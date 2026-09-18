"""API contract tests. No database, no API key: ask() is replaced."""

import pytest

from agent.present import DISCLAIMER
from api.app import MAX_QUESTION_CHARS, create_app
from api.serialize import answer_body, to_response


def _state(status="evaluated", kind="eligibility", **result):
    text = (f"Yes, you can take CPSC 221. [1]\n\nSources:\n"
            f"[1] CPSC 221 — Basic Algorithms — https://example.test/cpscv-221\n\n{DISCLAIMER}")
    return {
        "question": "can I take 221?",
        "route": {"intent": "eligibility", "scope_reason": "none", "rationale": "internal"},
        "result": {"kind": kind, "status": status, "codes": ["CPSC 221"],
                   "context": {"completed": ["CPSC 210"], "assumptions": [], "ignored": []},
                   **result},
        "answer": {"text": text, "lead": [], "sentences": [],
                   "sources": [{"n": 1, "id": "c1", "label": "CPSC 221 — Basic Algorithms",
                                "url": "https://example.test/cpscv-221"}],
                   "composed_by": "llm", "problems": [], "facts": "FACTS THE MODEL SAW",
                   "guard": {"action": "not needed"}},
        "log_id": 42,
    }


@pytest.fixture
def client():
    calls = []

    def fake_ask(question):
        calls.append(question)
        return _state(courses=[{"code": "CPSC 221", "found": True, "verdict": "SATISFIED"}])

    app = create_app(ask_fn=fake_ask)
    app.testing = True
    c = app.test_client()
    c.calls = calls
    return c


# ------------------------------------------------------------------ validation

def test_health_needs_nothing(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json == {"status": "ok"}


def test_ask_happy_path(client):
    r = client.post("/api/ask", json={"question": "  can I take 221?  "})
    assert r.status_code == 200
    assert client.calls == ["can I take 221?"]              # stripped
    assert r.json["status"] == "evaluated" and r.json["answered"] is True
    assert r.json["log_id"] == 42
    assert r.headers["X-Request-Id"] == r.json["request_id"]


@pytest.mark.parametrize("payload, fragment", [
    ({}, "must be a string"),
    ({"question": 5}, "must be a string"),
    ({"question": "   "}, "empty"),
    ({"question": "x" * (MAX_QUESTION_CHARS + 1)}, "under"),
    (["a list"], "JSON object"),
])
def test_ask_rejects_bad_questions(client, payload, fragment):
    r = client.post("/api/ask", json=payload)
    assert r.status_code == 400
    assert r.json["error"]["code"] == "invalid_question"
    assert fragment in r.json["error"]["message"]
    assert client.calls == []                                # never reached the pipeline


def test_ask_requires_json(client):
    r = client.post("/api/ask", data="question=hi")
    assert r.status_code == 415


def test_oversized_body_is_json_413(client):
    r = client.post("/api/ask", data="x" * 20_000, content_type="application/json")
    assert r.status_code == 413 and "error" in r.json


def test_unknown_route_is_json_404(client):
    r = client.get("/nope")
    assert r.status_code == 404 and r.json["error"]["code"] == "not_found"


def test_pipeline_crash_is_503_without_internals():
    def boom(_):
        raise RuntimeError("psycopg: password authentication failed for user advisor")

    app = create_app(ask_fn=boom)
    r = app.test_client().post("/api/ask", json={"question": "hi"})
    assert r.status_code == 503
    assert "psycopg" not in r.get_data(as_text=True)


# ------------------------------------------------------------------ response contract

def test_answer_body_drops_sources_and_disclaimer():
    text = _state()["answer"]["text"]
    assert answer_body(text) == "Yes, you can take CPSC 221. [1]"
    assert answer_body(f"Which course?\n\n{DISCLAIMER}") == "Which course?"


def test_response_keeps_internals_out():
    body = to_response(_state(hits=[{"section_path": "Regs > Repeating", "source_url": "u",
                                     "score": 0.9, "content": "VERBATIM POLICY TEXT"}],
                              kind="policy", status="ok"))
    flat = str(body)
    assert "VERBATIM POLICY TEXT" not in flat        # retrieved text stays server-side
    assert "FACTS THE MODEL SAW" not in flat         # composer input stays server-side
    assert "rationale" not in flat                   # router internals
    assert body["details"]["sections"] == [{"section_path": "Regs > Repeating", "source_url": "u"}]
    assert body["disclaimer"] == DISCLAIMER


def test_error_message_is_not_forwarded():
    body = to_response(_state(status="error", kind="error",
                              message="routing failed: APITimeoutError(...)"))
    assert body["answered"] is False
    assert "APITimeoutError" not in str(body)


def test_clarification_is_structured():
    body = to_response(_state(
        status="needs_clarification",
        ambiguous=[{"as_written": "320", "role": "target", "candidates": ["CPSC 320", "MATH 320"]}],
        message="'320' could be CPSC 320, MATH 320. Which did you mean?"))
    assert body["answered"] is False
    assert body["clarification"]["options"] == [
        {"as_written": "320", "candidates": ["CPSC 320", "MATH 320"]}]


def test_sets_become_lists():
    body = to_response(_state(extra={"b", "a"}))
    assert body["details"]["extra"] == ["a", "b"]
