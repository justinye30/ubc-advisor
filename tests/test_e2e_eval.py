"""End-to-end eval scoring (pure) and question-set hygiene."""

from pathlib import Path

import yaml

from agent import entities, router
from core.codes import find_codes
from eval.run_e2e_eval import (
    clarify_failures,
    declined,
    percentile,
    result_mismatches,
    score_answerable,
    text_failures,
)

QUESTIONS = yaml.safe_load((Path(__file__).parents[1] / "eval" / "e2e_questions.yaml").read_text())


def answer(text="", sources=(), sentences=(), remaining=()):
    return {"text": text, "sources": [{"url": u} for u in sources],
            "sentences": [{"text": s, "cites": []} for s in sentences],
            "guard": {"action": "passed", "remaining": list(remaining)}}


ELIG = {"kind": "eligibility", "status": "evaluated", "codes": ["CPSC 221"],
        "courses": [{"code": "CPSC 221", "verdict": "SATISFIED"}]}


# ---------- the question set ----------

def test_set_shape():
    assert len(QUESTIONS) == 50
    assert sum(1 for q in QUESTIONS if q.get("decline")) == 10
    assert len({q["id"] for q in QUESTIONS}) == 50
    assert all(q.get("intent") for q in QUESTIONS if not q.get("decline"))


def test_no_course_codes_shared_with_prompt_examples():
    prompt_codes = set(find_codes(router.SYSTEM_PROMPT)) | set(find_codes(entities.SYSTEM_PROMPT))
    eval_codes = {c for q in QUESTIONS for c in find_codes(q["question"])}
    assert not (prompt_codes & eval_codes), sorted(prompt_codes & eval_codes)


def test_no_questions_reused_from_other_eval_sets():
    root = Path(__file__).parents[1] / "eval"
    others = set()
    for name in ("routing_questions.yaml", "routing_holdout.yaml", "entities_questions.yaml",
                 "entities_holdout.yaml", "composer_cases.yaml"):
        others |= {q["question"].strip().lower() for q in yaml.safe_load((root / name).read_text())}
    assert not [q["id"] for q in QUESTIONS if q["question"].strip().lower() in others]


# ---------- scoring ----------

def test_matching_results():
    assert result_mismatches(ELIG, ELIG) == []


def test_verdict_mismatch_is_reported():
    got = {**ELIG, "courses": [{"code": "CPSC 221", "verdict": "INDETERMINATE"}]}
    assert result_mismatches(ELIG, got) == [
        "verdicts: got ['CPSC 221=INDETERMINATE'], expected ['CPSC 221=SATISFIED']"]


def test_status_mismatch_short_circuits():
    got = {**ELIG, "status": "requirements_only"}
    assert result_mismatches(ELIG, got) == ["status requirements_only, expected evaluated"]


def test_path_and_unlock_lists_are_compared_as_sets():
    path = {"kind": "path", "status": "ok", "codes": ["CPSC 404"], "verdict": "NOT_SATISFIED",
            "required_on_every_route": ["CPSC 304"], "ready_now": ["CPSC 221", "CPSC 213"]}
    assert result_mismatches(path, {**path, "ready_now": ["CPSC 213", "CPSC 221"]}) == []
    assert result_mismatches(path, {**path, "ready_now": ["CPSC 213"]}) == [
        "ready now: got ['CPSC 213'], expected ['CPSC 213', 'CPSC 221']"]


def test_text_checks():
    a = answer("It is limited to six credits.", sources=["https://cal/x/credit-ubc-and-elsewhere"])
    assert text_failures({"mentions": ["six|6"], "pages": ["credit-ubc-and-elsewhere"]}, a) == []
    assert text_failures({"mentions": ["72"]}, a) == ["doesn't mention '72'"]
    assert text_failures({"pages": ["registration"]}, a) == ["cites none of ['registration']"]
    assert text_failures({}, answer(remaining=["1: x"])) == ["guard left violations"]
    assert text_failures({}, None) == ["no answer"]


def test_clarification_must_offer_the_expected_courses():
    result = {"status": "needs_clarification",
              "ambiguous": [{"as_written": "320", "candidates": ["CPSC 320", "MATH 320"]}]}
    assert clarify_failures({"candidates": ["CPSC 320"]}, result) == []
    assert clarify_failures({"candidates": ["STAT 320"]}, result) == ["didn't offer ['STAT 320']"]


def test_declining():
    assert declined({"status": "refused"}, None) == "refused"
    assert declined({"status": "course_not_found"}, None) == "course_not_found"
    said = answer(sentences=["The calendar sources don't address tuition."])
    assert declined({"status": "ok"}, said) == "said the calendar doesn't cover it"
    assert declined({"status": "ok"}, answer(sentences=["It is six credits."])) is None


def test_answerable_scoring():
    case = {"intent": "eligibility"}
    route = {"intent": "eligibility"}
    assert score_answerable(case, route, ELIG, answer(), ELIG) == []
    assert score_answerable(case, {"intent": "policy"}, ELIG, answer(), ELIG)[0] == "routed to policy"
    refused = {"status": "refused"}
    assert "declined (refused)" in score_answerable(case, route, refused, answer(), None)
    assert score_answerable(case, None, ELIG, answer(), ELIG) == ["routing failed"]


def test_percentile():
    assert percentile([1, 2, 3, 4, 5], 0.5) == 3
    assert percentile([], 0.95) == 0.0
