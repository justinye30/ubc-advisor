"""One handler per intent. Each takes the graph state and returns a
structured `result` — facts for the composer (Step 14), never prose.

Until entity extraction (Step 13) exists, handlers only see course codes
written out in full ("CPSC 221") and no transcript. They say so in their
status rather than guessing.
"""

from core.codes import find_codes
from core.graph import PathView, always_required, ancestry, connect, dependents
from core.repo import get_course
from core.retrieval import search_policy
from core.transcript import Transcript

REFUSALS: dict[str, str] = {
    "advice": (
        "I can tell you what each course requires and what it leads to, but not "
        "which one you should take. That's a call for you and an academic advisor."
    ),
    "course_content": (
        "I only have what the Academic Calendar says — requirements and policies — "
        "not workload, difficulty, instructors, or reviews."
    ),
    "registration": (
        "Sections, schedules, seats, and registration dates aren't in the calendar "
        "data I use, and I can't register you. Check UBC's registration system."
    ),
    "personal_record": (
        "I can't see your record. Tell me which courses you've completed and I can "
        "check requirements against them."
    ),
    "other_institution": (
        "I only cover the UBC Vancouver Academic Calendar. For credit from other "
        "institutions, check UBC's transfer credit resources."
    ),
    "unrelated": (
        "I answer questions about UBC Vancouver course requirements and academic "
        "policy."
    ),
}

EXAMPLES = [
    "Can I take CPSC 221 with CPSC 110, 121 and 210?",
    "What does CPSC 213 unlock?",
    "Can I retake a course I already passed?",
]


def _needs_course(kind: str) -> dict:
    return {"result": {"kind": kind, "status": "needs_course", "codes": []}}


def _not_found(kind: str, code: str) -> dict:
    return {"result": {"kind": kind, "status": "course_not_found", "codes": [code]}}


def eligibility(state: dict) -> dict:
    codes = find_codes(state["question"])
    if not codes:
        return _needs_course("eligibility")
    courses = []
    for code in codes[:3]:
        c = get_course(code)
        if c is None:
            courses.append({"code": code, "found": False})
            continue
        courses.append({
            "code": c.code, "found": True, "title": c.title,
            "prereq_text": c.prereq_text, "extraction_status": c.extraction_status,
            "source_url": c.source_url,
        })
    # No transcript yet (Step 13), so no verdict — only the requirement itself.
    return {"result": {"kind": "eligibility", "status": "requirements_only",
                       "codes": codes[:3], "courses": courses}}


def policy(state: dict) -> dict:
    hits = search_policy(state["question"], k=5)
    return {"result": {
        "kind": "policy",
        "status": "ok" if hits else "no_results",
        "codes": find_codes(state["question"]),
        "hits": [
            {"section_path": h.section_path, "source_url": h.source_url,
             "score": round(h.score, 4), "content": h.content}
            for h in hits
        ],
    }}


def unlock(state: dict) -> dict:
    codes = find_codes(state["question"])
    if not codes:
        return _needs_course("unlock")
    code = codes[0]
    course = get_course(code)
    if course is None:
        return _not_found("unlock", code)
    with connect() as conn:
        deps = dependents(conn, code)
    return {"result": {
        "kind": "unlock", "status": "ok", "codes": [code],
        "title": course.title, "source_url": course.source_url,
        "required_by": [d.code for d in deps if not d.is_optional],
        "option_for": [d.code for d in deps if d.is_optional],
    }}


def path(state: dict) -> dict:
    codes = find_codes(state["question"])
    if not codes:
        return _needs_course("path")
    code = codes[0]
    course = get_course(code)
    if course is None:
        return _not_found("path", code)
    with connect() as conn:
        rows = ancestry(conn, code)
    view = PathView(code, course.prereq_tree, rows, Transcript())
    return {"result": {
        "kind": "path", "status": "ok", "codes": [code],
        "title": course.title, "source_url": course.source_url,
        "required_on_every_route": always_required(code, rows, stop_at=view.ready()),
        "tree": view.render(),
    }}


def out_of_scope(state: dict) -> dict:
    reason = state["route"]["scope_reason"]
    return {"result": {
        "kind": "out_of_scope", "status": "refused", "codes": [],
        "scope_reason": reason,
        "message": REFUSALS.get(reason, REFUSALS["unrelated"]),
        "examples": EXAMPLES,
    }}


def failed(state: dict) -> dict:
    return {"result": {
        "kind": "error", "status": "error", "codes": [],
        "message": state.get("error", "unknown error"),
    }}


HANDLERS = {
    "eligibility": eligibility,
    "policy": policy,
    "unlock": unlock,
    "path": path,
    "out_of_scope": out_of_scope,
}
