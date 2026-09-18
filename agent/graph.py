"""The question-answering graph.

    START → classify ─┬─ policy ───────────────────┐
                      ├─ out_of_scope ─────────────┤
                      ├─ extract ─┬─ eligibility ──┤
                      │           ├─ path ─────────┼→ compose → guard → END
                      │           ├─ unlock ───────┤
                      │           └─ clarify ──────┤
                      └─ failed ───────────────────┘

Only intents that need courses or a transcript pay for extraction. Every
branch ends in `compose`, which uses a template when no model is needed, and
`guard`, which checks each sentence against the facts before anything ships.
"""

import hashlib
import json
import logging
import time
from collections.abc import Callable
from typing import Required, TypedDict, cast

import anthropic
import psycopg
from langgraph.graph import END, START, StateGraph

from agent.composer import Answer, compose
from agent.entities import Entities, EntityError, extract, fill_missing_target
from agent.guard import guard
from agent.handlers import HANDLERS, clarify, failed
from agent.router import INTENTS, Route, RouteError, classify
from core.db import connection

log = logging.getLogger("agent")


NEEDS_ENTITIES = {"eligibility", "path", "unlock"}


class AdvisorState(TypedDict, total=False):
    question: Required[str]
    route: Route
    entities: Entities
    result: dict
    answer: Answer
    error: str
    log_id: int          # query_logs row, set by ask() when recording


def after_classify(state: AdvisorState) -> str:
    if state.get("error") or "route" not in state:
        return "failed"
    intent = state["route"]["intent"]
    return "extract" if intent in NEEDS_ENTITIES else intent


def after_extract(state: AdvisorState) -> str:
    route, entities = state.get("route"), state.get("entities")
    if state.get("error") or route is None or entities is None:
        return "failed"
    if entities["ambiguous"]:
        return "clarify"
    return route["intent"]


def build_graph(classify_fn: Callable[[str], Route] = classify,
                handlers: dict | None = None,
                extract_fn: Callable[[str], Entities] = extract,
                compose_fn: Callable[..., Answer] = compose,
                guard_fn: Callable[..., Answer] = guard):
    handlers = handlers or HANDLERS
    missing = set(INTENTS) - set(handlers)
    if missing:
        raise ValueError(f"no handler for intents: {sorted(missing)}")

    def classify_node(state: AdvisorState) -> dict:
        try:
            return {"route": classify_fn(state["question"])}
        except (RouteError, anthropic.APIError) as exc:
            return {"error": f"routing failed: {exc}"}

    def extract_node(state: AdvisorState) -> dict:
        try:
            entities = extract_fn(state["question"])
        except (EntityError, anthropic.APIError) as exc:
            return {"error": f"entity extraction failed: {exc}"}
        route = state.get("route")
        intent = route["intent"] if route else ""
        return {"entities": fill_missing_target(entities, intent)}

    def compose_node(state: AdvisorState) -> dict:
        return {"answer": compose_fn(state["question"], state.get("result", {}))}

    def guard_node(state: AdvisorState) -> dict:
        answer = state.get("answer")
        if answer is None:
            return {}
        return {"answer": guard_fn(state["question"], state.get("result", {}), answer, compose_fn)}

    g = StateGraph(AdvisorState)
    g.add_node("classify", classify_node)
    g.add_node("extract", extract_node)
    g.add_node("compose", compose_node)
    g.add_node("guard", guard_node)
    g.add_edge("compose", "guard")
    g.add_edge("guard", END)
    for intent in INTENTS:
        g.add_node(intent, handlers[intent])
        g.add_edge(intent, "compose")
    for name, default in (("clarify", clarify), ("failed", failed)):
        g.add_node(name, handlers.get(name, default))
        g.add_edge(name, "compose")

    g.add_edge(START, "classify")
    g.add_conditional_edges(
        "classify", after_classify,
        {**{i: i for i in INTENTS if i not in NEEDS_ENTITIES},
         "extract": "extract", "failed": "failed"},
    )
    g.add_conditional_edges(
        "extract", after_extract,
        {**{i: i for i in NEEDS_ENTITIES}, "clarify": "clarify", "failed": "failed"},
    )
    return g.compile()


_app = None


def pipeline_version() -> str:
    """Changes whenever any model, prompt, or schema in the pipeline changes.
    End-to-end results are only comparable across runs with the same version."""
    from agent import composer, entities, router
    parts = [
        router.PROMPT_VERSION,
        entities.ENTITY_MODEL, entities.SYSTEM_PROMPT, json.dumps(entities.ENTITY_SCHEMA, sort_keys=True),
        composer.COMPOSER_MODEL, composer.SYSTEM_PROMPT, json.dumps(composer.ANSWER_SCHEMA, sort_keys=True),
    ]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:10]


def get_app():
    global _app
    if _app is None:
        _app = build_graph()
    return _app


def _citations(state: AdvisorState) -> list[str]:
    """URLs the answer actually cites (not everything the handler retrieved)."""
    answer = state.get("answer")
    return [s["url"] for s in answer["sources"]] if answer else []


def log_query(state: AdvisorState, latency_ms: int) -> int | None:
    """Record every question and return the row id. Logging must never break an answer."""
    route = state.get("route")
    result = state.get("result", {})
    try:
        with connection() as conn:
            row = conn.execute(
                "INSERT INTO query_logs (question, route, verdict, latency_ms, citations, error) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (state["question"], route["intent"] if route else None,
                 result.get("status"), latency_ms,
                 json.dumps(_citations(state)), state.get("error")),
            ).fetchone()
            return row["id"] if row else None
    except psycopg.Error as exc:       # includes PoolTimeout
        log.warning("could not write query log: %s", exc)
        return None


def ask(question: str, app=None, record: bool = True) -> AdvisorState:
    started = time.monotonic()
    state = cast(AdvisorState, (app or get_app()).invoke({"question": question}))
    if record:
        log_id = log_query(state, int((time.monotonic() - started) * 1000))
        if log_id is not None:
            state["log_id"] = log_id
    return state
