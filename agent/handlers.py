"""One handler per intent. Each takes the graph state and returns a
structured `result` — facts for the composer (Step 14), never prose.

Eligibility, path, and unlock read `state["entities"]` (Step 13): the target
courses and the transcript the student described. Every result carries a
`context` block saying what was assumed or ignored, so the answer can say it.
"""

from agent.entities import Entities, to_transcript
from core.codes import IN_SCOPE_SUBJECTS, find_codes
from core.embeddings import EmbeddingError
from core.evaluator import evaluate
from core.graph import (
    PathView,
    always_required,
    ancestry,
    connect,
    dependents,
    unlocks_for,
)
from core.repo import get_course
from core.retrieval import search_policy
from core.sweep import sweep
from core.transcript import Transcript

LIST_CAP = 25

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


def _context(e: Entities) -> dict:
    """What the answer should say about how the question was read."""
    return {
        "completed": e["completed"],
        "in_progress": e["in_progress"],
        "grades": {**e["grades"], **{k: f"{v[0]}–{v[1]}%" for k, v in e["grade_ranges"].items()}},
        "year": e["year"],
        "programs": e["programs"],
        "transcript_given": e["transcript_given"],
        "assumptions": e["assumptions"],
        "ignored": e["rejected"],
    }


def _result(kind: str, status: str, e: Entities, **fields) -> dict:
    return {"result": {"kind": kind, "status": status, "codes": e["targets"],
                       "context": _context(e), **fields}}


def _verdict(tree: dict | None, extraction_status: str, e: Entities) -> dict:
    if tree is None:
        if extraction_status == "no_prereq":
            return {"verdict": "NO_PREREQUISITES"}
        return {"verdict": "UNKNOWN", "summary": f"requirements not parsed ({extraction_status})"}
    if not e["transcript_given"]:
        return {}
    r = evaluate(tree, to_transcript(e))
    return {
        "verdict": r.state.value,
        "summary": r.summary,
        "reasons": [{"state": x.state.value, "text": x.text} for x in r.reasons],
    }


def eligibility(state: dict) -> dict:
    e: Entities = state["entities"]
    if not e["targets"]:
        if not e["transcript_given"]:
            return _result("eligibility", "needs_course", e)
        return _sweep(e)

    courses = []
    for code in e["targets"][:3]:
        c = get_course(code)
        if c is None:
            courses.append({"code": code, "found": False})
            continue
        courses.append({
            "code": c.code, "found": True, "title": c.title,
            "prereq_text": c.prereq_text, "extraction_status": c.extraction_status,
            "source_url": c.source_url,
            **_verdict(c.prereq_tree, c.extraction_status, e),
        })
    if not any(c["found"] for c in courses):
        # Same status as unlock/path use, so "that course isn't in my data"
        # reads as declining rather than answering.
        return _result("eligibility", "course_not_found", e, courses=courses)
    status = "evaluated" if e["transcript_given"] else "requirements_only"
    return _result("eligibility", status, e, courses=courses)


def _sweep(e: Entities) -> dict:
    t = to_transcript(e)
    subjects = {c.split()[0] for c in t.completed} & set(IN_SCOPE_SUBJECTS) or set(IN_SCOPE_SUBJECTS)
    s = sweep(t, subjects)
    return _result(
        "eligibility", "sweep", e,
        subjects=sorted(subjects),
        eligible=[c.code for c in s.eligible][:LIST_CAP],
        no_prereq=[c.code for c in s.no_prereq][:LIST_CAP],
        to_confirm=[{"code": c.code, "summary": r.summary} for c, r in s.to_confirm][:LIST_CAP],
        counts={"eligible": len(s.eligible), "no_prereq": len(s.no_prereq),
                "to_confirm": len(s.to_confirm), "not_yet": len(s.not_yet)},
    )


def policy(state: dict) -> dict:
    try:
        hits = search_policy(state["question"], k=5)
    except EmbeddingError as exc:
        # The embedding service is down or rate-limited: fail this answer
        # cleanly rather than the whole request.
        return {"result": {"kind": "error", "status": "error", "codes": [],
                           "message": f"policy search unavailable: {exc}"}}
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
    e: Entities = state["entities"]
    if not e["targets"]:
        return _result("unlock", "needs_course", e)
    code = e["targets"][0]
    course = get_course(code)
    if course is None:
        return _result("unlock", "course_not_found", e)
    with connect() as conn:
        deps = dependents(conn, code)
    base = {"title": course.title, "source_url": course.source_url}

    if not e["transcript_given"]:
        return _result("unlock", "ok", e, **base,
                       required_by=[d.code for d in deps if not d.is_optional],
                       option_for=[d.code for d in deps if d.is_optional])

    # "What does taking X open up?" — compare against a record without X,
    # even when the student has already taken it or is taking it now.
    t = to_transcript(e)
    already = code in t.completed
    before = Transcript(completed=t.completed - {code},
                        grades={k: v for k, v in t.grades.items() if k != code},
                        grade_ranges={k: v for k, v in t.grade_ranges.items() if k != code},
                        credits=dict(t.credits), year=t.year, programs=set(t.programs))
    u = unlocks_for(code, before, deps)
    return _result(
        "unlock", "personal", e, **base, already_taken=already,
        newly_eligible=[d.code for d, _ in u.newly_eligible],
        to_confirm=[{"code": d.code, "summary": r.summary} for d, r in u.to_confirm],
        still_blocked=[{"code": d.code, "summary": r.summary} for d, r in u.still_blocked],
        already_eligible=[d.code for d in u.already_eligible],
    )


def path(state: dict) -> dict:
    e: Entities = state["entities"]
    if not e["targets"]:
        return _result("path", "needs_course", e)
    code = e["targets"][0]
    course = get_course(code)
    if course is None:
        return _result("path", "course_not_found", e)
    t = to_transcript(e)
    with connect() as conn:
        rows = ancestry(conn, code, stop_at=t.completed)
    view = PathView(code, course.prereq_tree, rows, t)
    tree = view.render()
    required = [c for c in always_required(code, rows, stop_at=t.completed | view.ready())
                if c not in t.completed]
    return _result(
        "path", "ok", e,
        title=course.title, source_url=course.source_url,
        **_verdict(course.prereq_tree, course.extraction_status, e),
        required_on_every_route=required,
        ready_now=view.ready_shown,
        hidden_okanagan=view.hidden_okanagan,
        tree=tree,
    )


def out_of_scope(state: dict) -> dict:
    reason = state["route"]["scope_reason"]
    return {"result": {
        "kind": "out_of_scope", "status": "refused", "codes": [],
        "scope_reason": reason,
        "message": REFUSALS.get(reason, REFUSALS["unrelated"]),
        "examples": EXAMPLES,
    }}


def clarify(state: dict) -> dict:
    e: Entities = state["entities"]
    return {"result": {
        "kind": state["route"]["intent"], "status": "needs_clarification",
        "codes": e["targets"], "context": _context(e),
        "ambiguous": e["ambiguous"],
        "message": "; ".join(
            f"'{a['as_written']}' could be {', '.join(a['candidates'])}" for a in e["ambiguous"]
        ) + ". Which did you mean?",
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
