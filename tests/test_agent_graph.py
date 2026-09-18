"""Graph wiring tests: fake classifier, extractor, and handlers. No DB, no API."""

from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest

from agent.composer import Answer
from agent.entities import Entities, EntityError
from agent.graph import NEEDS_ENTITIES, build_graph
from agent.handlers import REFUSALS, out_of_scope
from agent.router import INTENTS, Route, RouteError


def entities(**overrides: Any) -> Entities:
    base: dict[str, Any] = {
        "targets": ["CPSC 221"], "completed": [], "grades": {}, "grade_ranges": {},
        "in_progress": [], "year": None, "programs": [], "transcript_given": False,
        "ambiguous": [], "assumptions": [], "rejected": [], "unused": [],
    }
    return Entities(**{**base, **overrides})


def fake_handlers():
    def make(name):
        return lambda state: {"result": {"kind": name, "status": "ok",
                                         "saw_entities": "entities" in state}}
    handlers = {i: make(i) for i in INTENTS}
    handlers["out_of_scope"] = out_of_scope   # the real one needs no DB
    return handlers


def route(intent: str, scope: str = "none") -> Callable[[str], Route]:
    def classify(question: str) -> Route:
        return Route(intent=intent, scope_reason=scope, rationale="test")
    return classify


class CountingExtractor:
    def __init__(self, result: Entities | None = None, error: Exception | None = None):
        self.calls = 0
        self.result: Entities = result or entities()
        self.error = error

    def __call__(self, question: str) -> Entities:
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def fake_compose(question: str, result: dict) -> Answer:
    return Answer(text=f"answer for {result.get('kind')}", lead=[], sentences=[], sources=[],
                  composed_by="test", problems=[], facts="")


def graph(classify, handlers=None, extractor=None):
    return build_graph(classify, handlers or fake_handlers(),
                       extractor or CountingExtractor(), fake_compose)


def app(intent: str, extractor: CountingExtractor | None = None, scope: str = "none"):
    return graph(route(intent, scope), extractor=extractor)


@pytest.mark.parametrize("intent", sorted(NEEDS_ENTITIES))
def test_entity_intents_extract_then_reach_their_handler(intent):
    ex = CountingExtractor()
    state = app(intent, ex).invoke({"question": "q"})
    assert ex.calls == 1
    assert state["result"]["kind"] == intent
    assert state["result"]["saw_entities"] is True


@pytest.mark.parametrize("intent", ["policy", "out_of_scope"])
def test_other_intents_skip_extraction(intent):
    ex = CountingExtractor()
    state = app(intent, ex).invoke({"question": "q"})
    assert ex.calls == 0
    assert state["result"]["kind"] == intent
    assert "entities" not in state


def test_ambiguous_course_goes_to_clarify_not_the_handler():
    ex = CountingExtractor(entities(targets=[], ambiguous=[
        {"as_written": "320", "role": "target", "candidates": ["CPSC 320", "MATH 320"]}]))
    result = app("eligibility", ex).invoke({"question": "can I take 320?"})["result"]
    assert result["status"] == "needs_clarification"
    assert "CPSC 320, MATH 320" in result["message"]


def test_extraction_error_goes_to_failed():
    ex = CountingExtractor(error=EntityError("bad json"))
    result = app("path", ex).invoke({"question": "q"})["result"]
    assert result["kind"] == "error"
    assert "entity extraction failed" in result["message"]


def test_out_of_scope_uses_the_template_for_its_reason():
    result = app("out_of_scope", scope="advice").invoke({"question": "320 or 322?"})["result"]
    assert result["status"] == "refused"
    assert result["message"] == REFUSALS["advice"]


def test_every_scope_reason_has_a_refusal():
    from agent.router import SCOPE_REASONS
    assert set(SCOPE_REASONS) - {"none"} <= set(REFUSALS)


def test_routing_error_goes_to_failed_not_a_handler():
    def broken(q: str) -> Route:
        raise RouteError("bad json")
    state = graph(broken).invoke({"question": "q"})
    assert "route" not in state
    assert state["result"]["kind"] == "error"
    assert "bad json" in state["result"]["message"]


def test_api_error_goes_to_failed():
    def down(q: str) -> Route:
        # The SDK is built on httpx2, so its errors expect an httpx2 request.
        raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))
    state = graph(down).invoke({"question": "q"})
    assert state["result"]["kind"] == "error"


def test_bugs_are_not_swallowed():
    def buggy(q: str) -> Route:
        raise KeyError("oops")
    with pytest.raises(KeyError):
        graph(buggy).invoke({"question": "q"})


def test_missing_handler_is_caught_at_build_time():
    handlers = fake_handlers()
    del handlers["path"]
    with pytest.raises(ValueError, match="path"):
        graph(route("path"), handlers)


def test_extract_node_fills_a_missing_target_from_the_question():
    ex = CountingExtractor(entities(targets=[], unused=["MATH 200"]))
    seen: dict = {}

    def unlock(state):
        seen["targets"] = state["entities"]["targets"]
        return {"result": {"kind": "unlock", "status": "ok"}}

    handlers = {**fake_handlers(), "unlock": unlock}
    graph(route("unlock"), handlers, ex).invoke({"question": "Which courses need MATH 200?"})
    assert seen["targets"] == ["MATH 200"]


@pytest.mark.parametrize("intent", INTENTS)
def test_every_branch_ends_in_compose_then_guard(intent):
    state = app(intent).invoke({"question": "q"})
    assert state["answer"]["text"] == f"answer for {state['result']['kind']}"
    assert state["answer"].get("guard", {}).get("action") == "not needed"


def test_failures_and_clarifications_are_composed_too():
    def broken(q: str) -> Route:
        raise RouteError("x")
    assert graph(broken).invoke({"question": "q"})["answer"]["text"] == "answer for error"
    ex = CountingExtractor(entities(targets=[], ambiguous=[
        {"as_written": "320", "role": "target", "candidates": ["CPSC 320", "MATH 320"]}]))
    assert app("path", ex).invoke({"question": "q"})["answer"]["text"] == "answer for path"


def test_policy_search_outage_becomes_an_error_answer(monkeypatch):
    from agent import handlers
    from core.embeddings import EmbeddingError

    def down(*a, **k):
        raise EmbeddingError("voyage 503")
    monkeypatch.setattr(handlers, "search_policy", down)
    result = handlers.policy({"question": "Can I retake a course?"})["result"]
    assert result["status"] == "error" and "voyage 503" in result["message"]


def test_unknown_course_reads_as_declining():
    from agent import handlers
    e = entities(targets=["CPSC 999"], transcript_given=True, completed=["CPSC 110"])
    monkey = handlers.get_course
    handlers.get_course = lambda code: None
    try:
        result = handlers.eligibility({"question": "Can I take CPSC 999?", "entities": e})["result"]
    finally:
        handlers.get_course = monkey
    assert result["status"] == "course_not_found"
