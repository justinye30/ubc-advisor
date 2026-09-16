"""The question-answering graph.

    START → classify ─┬─ eligibility ─┐
                      ├─ policy ──────┤
                      ├─ path ────────┤
                      ├─ unlock ──────┼→ END
                      ├─ out_of_scope ┤
                      └─ failed ──────┘

Later steps add nodes (entity extraction before the handlers, composer and
citation guard after them) without changing this shape. LangGraph makes the
branches explicit now and allows loops later (e.g. retrieval found nothing →
reformulate → retry).
"""

import json
import logging
import os
import time
from collections.abc import Callable
from typing import Required, TypedDict, cast

import anthropic
import psycopg
from langgraph.graph import END, START, StateGraph

from agent.handlers import HANDLERS, failed
from agent.router import INTENTS, Route, RouteError, classify

log = logging.getLogger("agent")


class AdvisorState(TypedDict, total=False):
    question: Required[str]
    route: Route
    result: dict
    error: str


def pick_branch(state: AdvisorState) -> str:
    if state.get("error") or "route" not in state:
        return "failed"
    return state["route"]["intent"]


def build_graph(classify_fn: Callable[[str], Route] = classify,
                handlers: dict | None = None):
    handlers = handlers or HANDLERS
    missing = set(INTENTS) - set(handlers)
    if missing:
        raise ValueError(f"no handler for intents: {sorted(missing)}")

    def classify_node(state: AdvisorState) -> dict:
        try:
            return {"route": classify_fn(state["question"])}
        except (RouteError, anthropic.APIError) as exc:
            return {"error": f"routing failed: {exc}"}

    g = StateGraph(AdvisorState)
    g.add_node("classify", classify_node)
    for intent in INTENTS:
        g.add_node(intent, handlers[intent])
        g.add_edge(intent, END)
    g.add_node("failed", handlers.get("failed", failed))
    g.add_edge("failed", END)

    g.add_edge(START, "classify")
    g.add_conditional_edges(
        "classify", pick_branch,
        {**{i: i for i in INTENTS}, "failed": "failed"},
    )
    return g.compile()


_app = None


def get_app():
    global _app
    if _app is None:
        _app = build_graph()
    return _app


def _citations(result: dict) -> list[str]:
    urls = [h["source_url"] for h in result.get("hits", [])]
    urls += [c["source_url"] for c in result.get("courses", []) if c.get("source_url")]
    if result.get("source_url"):
        urls.append(result["source_url"])
    return list(dict.fromkeys(urls))


def log_query(state: AdvisorState, latency_ms: int) -> None:
    """Record every question. Logging must never break an answer."""
    route = state.get("route")
    result = state.get("result", {})
    try:
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            conn.execute(
                "INSERT INTO query_logs (question, route, verdict, latency_ms, citations, error) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (state["question"], route["intent"] if route else None,
                 result.get("status"), latency_ms,
                 json.dumps(_citations(result)), state.get("error")),
            )
    except psycopg.Error as exc:
        log.warning("could not write query log: %s", exc)


def ask(question: str, app=None, record: bool = True) -> AdvisorState:
    started = time.monotonic()
    state = cast(AdvisorState, (app or get_app()).invoke({"question": question}))
    if record:
        log_query(state, int((time.monotonic() - started) * 1000))
    return state

