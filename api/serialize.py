"""Turn the agent's final state into the JSON the web UI reads.

This is an explicit contract, not a dump of internal state:

- The UI gets stable field names even when handler internals change.
- Retrieved policy text (result["hits"][*]["content"]) stays on the server.
  The answer cites those sections by URL; the browser doesn't need copies.
- Internal error text ("routing failed: <exception>") never reaches the
  client. The composed answer already says something human.
"""

from dataclasses import asdict, is_dataclass

from agent.present import DISCLAIMER

# Statuses where the system is asking, declining, or failing rather than answering.
NOT_ANSWERS = {"needs_course", "needs_clarification", "course_not_found",
               "refused", "no_results", "error"}

# Handler fields the web UI renders, per kind. Everything else stays on the
# server. Step 17 passed handler fields through; Step 18 showed which are used.
DETAIL_FIELDS = {
    "eligibility": ("courses", "subjects", "eligible", "no_prereq", "to_confirm", "counts"),
    "path": ("title", "source_url", "verdict", "summary", "reasons",
             "required_on_every_route", "ready_now", "tree", "hidden_okanagan"),
    "unlock": ("title", "source_url", "required_by", "option_for", "already_taken",
               "newly_eligible", "to_confirm", "still_blocked", "already_eligible"),
}
COURSE_FIELDS = ("code", "found", "title", "prereq_text", "source_url",
                 "verdict", "summary", "reasons")


def plain(x):
    """Make a value JSON-safe: sets and tuples become lists, dataclasses dicts."""
    if is_dataclass(x) and not isinstance(x, type):
        return plain(asdict(x))
    if isinstance(x, dict):
        return {str(k): plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [plain(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return sorted(plain(v) for v in x)
    return x


def answer_body(text: str) -> str:
    """The prose of the answer without the Sources list and disclaimer footer.

    present.render() appends "\\n\\nSources:\\n..." and then the disclaimer.
    The UI renders both from structured fields instead.
    """
    body = text.strip().removesuffix(DISCLAIMER)
    return body.split("\n\nSources:\n", 1)[0].strip()


def details(result: dict) -> dict:
    """The handler-specific part of the response, allow-listed per kind."""
    out = {k: result[k] for k in DETAIL_FIELDS.get(result.get("kind"), ()) if k in result}
    if "courses" in out:
        out["courses"] = [{k: c[k] for k in COURSE_FIELDS if k in c} for c in out["courses"]]
    return out


def to_response(state: dict) -> dict:
    result = state.get("result") or {}
    answer = state.get("answer") or {}
    route = state.get("route") or {}
    status = result.get("status", "error")

    body = {
        "status": status,
        "answered": status not in NOT_ANSWERS,
        "intent": route.get("intent"),
        "kind": result.get("kind"),
        "codes": result.get("codes", []),
        "answer": {
            "text": answer_body(answer.get("text", "")),
            "sources": [{"n": s["n"], "label": s["label"], "url": s["url"]}
                        for s in answer.get("sources", [])],
            "composed_by": answer.get("composed_by"),
            "guard": (answer.get("guard") or {}).get("action"),
        },
        "disclaimer": DISCLAIMER,
        "context": result.get("context"),   # how the question was read: history, assumptions, ignored
        "log_id": state.get("log_id"),
    }

    if status == "needs_clarification":
        body["clarification"] = {
            "message": result.get("message"),
            "options": [{"as_written": a["as_written"], "candidates": a["candidates"]}
                        for a in result.get("ambiguous", [])],
        }
    if status == "refused":
        body["refusal"] = {"message": result.get("message"),
                           "examples": result.get("examples", [])}

    body["details"] = details(result)
    return plain(body)
