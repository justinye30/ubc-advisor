"""Graph wiring tests: a fake classifier and fake handlers, no DB, no API."""

import anthropic
import httpx
import pytest

from agent.graph import build_graph
from agent.handlers import REFUSALS, out_of_scope
from agent.router import INTENTS, RouteError


def fake_handlers():
    def make(name):
        return lambda state: {"result": {"kind": name, "status": "ok"}}
    handlers = {i: make(i) for i in INTENTS}
    handlers["out_of_scope"] = out_of_scope   # the real one needs no DB
    return handlers


def route(intent, scope="none"):
    return lambda q: {"intent": intent, "scope_reason": scope, "rationale": "test"}


@pytest.mark.parametrize("intent", [i for i in INTENTS if i != "out_of_scope"])
def test_each_intent_reaches_its_handler(intent):
    app = build_graph(route(intent), fake_handlers())
    state = app.invoke({"question": "q"})
    assert state["route"]["intent"] == intent
    assert state["result"]["kind"] == intent


def test_out_of_scope_uses_the_template_for_its_reason():
    app = build_graph(route("out_of_scope", "advice"), fake_handlers())
    result = app.invoke({"question": "should I take 320 or 322?"})["result"]
    assert result["status"] == "refused"
    assert result["message"] == REFUSALS["advice"]


def test_every_scope_reason_has_a_refusal():
    from agent.router import SCOPE_REASONS
    assert set(SCOPE_REASONS) - {"none"} <= set(REFUSALS)


def test_routing_error_goes_to_failed_not_a_handler():
    def broken(q):
        raise RouteError("bad json")
    state = build_graph(broken, fake_handlers()).invoke({"question": "q"})
    assert "route" not in state
    assert state["result"]["kind"] == "error"
    assert "bad json" in state["result"]["message"]


def test_api_error_goes_to_failed():
    def down(q):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    state = build_graph(down, fake_handlers()).invoke({"question": "q"})
    assert state["result"]["kind"] == "error"


def test_bugs_are_not_swallowed():
    def buggy(q):
        raise KeyError("oops")
    with pytest.raises(KeyError):
        build_graph(buggy, fake_handlers()).invoke({"question": "q"})


def test_missing_handler_is_caught_at_build_time():
    handlers = fake_handlers()
    del handlers["path"]
    with pytest.raises(ValueError, match="path"):
        build_graph(route("path"), handlers)
