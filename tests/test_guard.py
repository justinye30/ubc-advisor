"""Citation guard tests.

The first block replays the eight sentences hand-classified in Step 14: one
real error (CPEN 212 "can take immediately") and seven non-problems that the
Step 14 phrase checks flagged. The guard must catch exactly the one.
"""

import pytest

from agent.composer import Answer
from agent.guard import check_answer, clauses, guard
from agent.present import build_facts

CTX_221 = {"completed": ["CPSC 210", "MATH 226"], "in_progress": [], "grades": {"MATH 226": 61},
           "year": None, "programs": [], "transcript_given": True, "assumptions": [], "ignored": []}
CTX_340 = {**CTX_221, "completed": ["CPSC 221", "MATH 200"], "grades": {}, "year": 2}
CTX_404 = {**CTX_221, "completed": ["CPSC 110", "CPSC 121", "CPSC 210"], "grades": {}}

CANT_TELL_221 = {
    "kind": "eligibility", "status": "evaluated", "codes": ["CPSC 221"], "context": CTX_221,
    "courses": [{"code": "CPSC 221", "found": True, "title": "Algorithms",
                 "prereq_text": "One of CPSC_V 210, CPEN_V 221 and either (a) one of CPSC_V 121, "
                                "MATH_V 220, MATH_O 220 or (b) a score of 68% or higher in MATH_V 226",
                 "extraction_status": "parsed", "source_url": "https://cal/221",
                 "verdict": "INDETERMINATE", "summary": "x",
                 "reasons": [{"state": "SATISFIED", "text": "CPSC 210: completed"},
                             {"state": "NOT_SATISFIED", "text": "CPSC 121: not completed"},
                             {"state": "NOT_SATISFIED", "text": "MATH 220: not completed"},
                             {"state": "INDETERMINATE", "text": "MATH_O 220: Okanagan course"},
                             {"state": "NOT_SATISFIED", "text": "MATH 226: 61% < 68% required"}]}],
}
CANT_TELL_340 = {
    "kind": "eligibility", "status": "evaluated", "codes": ["CPSC 340"], "context": CTX_340,
    "courses": [{"code": "CPSC 340", "found": True, "title": "ML",
                 "prereq_text": "All of (a) CPSC_V 221; (b) one of MATH_V 152, MATH_V 221, MATH_V 223, "
                                "MATH_O 222; (c) one of MATH_V 200, ...; (d) one of STAT_V 241, STAT_V 251, "
                                "MATH_V 302, STAT_V 302, MATH_V 318, ECON_V 325, ECON_V 327, STAT_O 302",
                 "extraction_status": "parsed", "source_url": "https://cal/340",
                 "verdict": "INDETERMINATE", "summary": "x", "reasons": []}],
}
PATH_404 = {
    "kind": "path", "status": "ok", "codes": ["CPSC 404"], "context": CTX_404,
    "title": "Advanced Relational Databases", "source_url": "https://cal/404",
    "verdict": "NOT_SATISFIED", "summary": "CPSC 304: not completed",
    "reasons": [{"state": "NOT_SATISFIED", "text": "CPSC 304: not completed"}],
    "required_on_every_route": ["CPSC 304"], "ready_now": ["CPSC 221", "DSCI 221", "CPSC 213"],
    "hidden_okanagan": 0,
    "tree": ["├─ · CPSC 304   required",
             "│  ├─ → CPSC 221   option   ready to take",
             "│  └─ → DSCI 221   option   ready to take",
             "├─ · CPEN 212   option   (not needed now: another option is ready)",
             "├─ → CPSC 213   option   ready to take"],
}


def policy(text):
    return {"kind": "policy", "status": "ok", "codes": [],
            "hits": [{"section_path": "B.Sc. > Rules", "source_url": "https://cal/p", "score": 0.6,
                      "content": "B.Sc. > Rules\n\n" + text}]}


RETAKE = policy("A student who has passed a course will not be permitted to repeat that course for "
                "higher standing. Students who change specialization should consult academic advisors "
                "in the department and Science Advising.")
LOP = policy("Study on a Letter of Permission is limited to six credits. Students with unusual "
             "circumstances should present their case to an Advisor in Science Advising.")


def answer(*sentences) -> Answer:
    return Answer(text="", lead=[], sentences=[{"text": t, "cites": c} for t, c in sentences],
                  sources=[], composed_by="llm", problems=[], facts="")


def flags(result, text, cites=("check",)):
    return check_answer(answer((text, list(cites))), result, build_facts("q", result)).get(0, [])


# ---------- the Step 14 classification, replayed ----------

NOT_PROBLEMS = [
    (CANT_TELL_221, ("As a result, we cannot confirm you meet the prerequisites for CPSC 221 "
                    "based on the information available."), ["check"]),
    (CANT_TELL_340, ("Whether you can take CPSC 340 depends on whether you completed MATH_O 222 or one "
                    "of the other linear algebra options."), ["check", "S1"]),
    (CANT_TELL_340, ("You satisfy two of the four prerequisite requirements for CPSC 340: you have "
                    "completed CPSC 221 and MATH 200, which cover requirements (a) and (c)."),
     ["S1", "you", "check"]),
    (PATH_404, ("CPSC 304 itself has two prerequisite options — you can take either CPSC 221 or "
               "DSCI 221 — and you're ready for both of those right now."), ["check"]),
    (RETAKE, ("The only exception mentioned is for students who change specialization and need to "
             "attempt a course that shares credit exclusion with one already passed, in which case "
             "they should consult academic advisors."), ["S1"]),
    (LOP, ("If you have unusual personal circumstances requiring more than six credits elsewhere, "
          "you should present your case to an Advisor in Science Advising for consideration."), ["S1"]),
    (PATH_404, ("Based on what you've told us, you don't meet the listed prerequisites for CPSC 404 "
               "because you haven't completed CPSC 304, which is required."), ["you", "check"]),
]


UNLOCK_221 = {
    "kind": "unlock", "status": "personal", "codes": ["CPSC 221"], "context": CTX_404,
    "title": "Algorithms", "source_url": "https://cal/221",
    "newly_eligible": ["CPEN 441", "CPSC 304", "CPSC 322"],
    "to_confirm": [{"code": "CPSC 314", "summary": "MATH 200: not completed"}],
    "still_blocked": [{"code": c, "summary": "CPSC 213: not completed"}
                      for c in ["CPSC 310", "CPSC 411", "CPSC 313", "CPSC 317"]],
    "already_eligible": [],
}

# From the guarded eval (two false positives on unseen drafts).
NOT_PROBLEMS += [
    (UNLOCK_221, ("Courses including CPSC 310, CPSC 411, CPSC 313, and CPSC 317 would still require "
                 "CPSC 213, which is not among the courses you've completed."), ["check"]),
    (PATH_404, ("To take CPSC 304, you need one of CPSC 221 or DSCI 221, both of which you're ready "
               "to take now given your completed courses."), ["check"]),
    (CANT_TELL_221, ("You don't meet all the prerequisites for CPSC 221 based on what we can verify: "
                    "your MATH 226 grade of 61% is below the required 68%."), ["check"]),
]

# From the first rescore of the Step 14 baseline (two false positives).
NOT_PROBLEMS += [
    (CANT_TELL_221, ("You meet the first prerequisite (CPSC 210 completed), but the second "
                    "prerequisite—requiring either a discrete math course or a 68% or higher in "
                    "MATH 226—cannot be fully verified from what we have."), ["check"]),
    (CANT_TELL_221, ("The calendar requires either CPSC 121, MATH 220, or MATH_O 220, or a score of 68% "
                    "or higher in MATH 226 for CPSC 221, and you completed CPSC 210 which satisfies "
                    "the first part of the prerequisites."), ["S1", "you"]),
]


@pytest.mark.parametrize("result,text,cites", NOT_PROBLEMS)
def test_step14_non_problems_are_not_flagged(result, text, cites):
    assert flags(result, text, cites) == []


def test_step14_real_error_is_caught_for_the_right_reason():
    text = ("CPSC 404 also lists other prerequisite options including CPSC 213 and CPEN 212, "
            "both of which you can take immediately.")
    assert flags(PATH_404, text) == ["says the student can take CPEN 212, which isn't ready"]


def test_rescore_real_problem_availability_without_history_is_caught():
    no_history = {**PATH_404, "codes": ["CPSC 340"], "verdict": None, "reasons": [],
                  "ready_now": [], "context": {**CTX_404, "completed": [], "transcript_given": False},
                  "tree": ["├─ · CPSC 221   option", "├─ · DSCI 221   option",
                           "├─ · MATH 220   option", "└─ · MATH 221   option"]}
    text = ("However, the course has many optional prerequisites organized by topic: you can take "
            "CPSC 221, DSCI 221, or combinations of mathematics courses (such as MATH 220 and MATH 221).")
    assert flags(no_history, text) == ["says the student can take CPSC 221, which isn't ready",
                                       "says the student can take DSCI 221, which isn't ready"]


# ---------- verdict claims ----------

def test_all_of_the_requirements_is_a_full_claim():
    assert flags(CANT_TELL_221, "You meet all of the requirements for CPSC 221.") == [
        "says 'You meet' but the verdict isn't a yes"]


def test_claim_scope_follows_the_verb():
    assert flags(PATH_404, "CPEN 212 is open to you.") == [
        "says the student can take CPEN 212, which isn't ready"]
    assert flags(PATH_404, "CPSC 304 needs CPSC 221; you can take CPSC 213 now.") == []
    assert flags(PATH_404, "You have completed CPSC 210, unlike CPSC 213.") == []

def test_guarded_eval_real_problem_is_caught():
    text = ("You cannot take CPSC 221 because you have two unsatisfied prerequisites: CPSC 121 is "
            "not completed, and your MATH 226 grade of 61% falls short of the 68% required.")
    assert flags(CANT_TELL_221, text) == ["says 'You cannot take' but the verdict isn't a no"]


def test_trailing_list():
    from agent.guard import trailing_list
    assert trailing_list("To take CPSC 304, you need one of CPSC 221 or DSCI 221") == ["CPSC 221", "DSCI 221"]
    assert trailing_list("CPSC 313, and CPSC 317 would still require CPSC 213") == ["CPSC 213"]
    assert trailing_list("including CPSC 213, CPEN 212, and CPSC 261") == ["CPSC 213", "CPEN 212", "CPSC 261"]
    assert trailing_list("no courses here") == []


def test_full_contradiction_of_a_cant_tell_is_caught():
    text = ("You don't meet the stated prerequisites for CPSC 221 because your MATH 226 "
            "score of 61% falls below the required 68%.")
    assert flags(CANT_TELL_221, text) == ["says 'You don't meet' but the verdict isn't a no"]


def test_unqualified_yes_under_a_no_is_caught():
    assert flags(PATH_404, "So you can take CPSC 404.") == ["says 'you can take' but the verdict isn't a yes"]


def test_claims_about_the_student_with_no_course_named_count_as_the_target():
    assert flags(CANT_TELL_221, "In short, you're eligible.")


# ---------- availability and history ----------

def test_ready_courses_may_be_offered():
    assert flags(PATH_404, "You can take CPSC 213 now.") == []


def test_relative_clause_about_another_course_is_not_an_availability_claim():
    assert flags(PATH_404, "You can take CPSC 221 now, which is one option for CPSC 304.") == []


def test_general_unlock_answers_cannot_promise_any_course():
    unlock = {"kind": "unlock", "status": "ok", "codes": ["CPSC 213"], "context": {
        **CTX_221, "completed": [], "transcript_given": False},
        "title": "Systems", "source_url": "https://cal/213", "required_by": ["CPSC 313"],
        "option_for": []}
    assert flags(unlock, "CPSC 313 requires CPSC 213.") == []
    assert flags(unlock, "You can take CPSC 313 after that.") == []            # hedged
    assert flags(unlock, "You can take CPSC 313.") == [
        "says the student can take CPSC 313, which isn't ready"]


def test_invented_history_is_caught():
    assert flags(PATH_404, "You have completed CPSC 213.") == [
        "says the student completed CPSC 213, which they didn't mention"]
    assert flags(PATH_404, "You haven't completed CPSC 210 yet.") == [
        "says the student hasn't completed CPSC 210, but they have"]
    assert flags(PATH_404, "You haven't completed CPSC 304.") == []


# ---------- grounding ----------

def test_advice_is_only_allowed_when_the_cited_source_says_it():
    text = "You should consult academic advisors."
    assert flags(RETAKE, text, ["S1"]) == []
    assert len(flags(RETAKE, text, ["check"])) == 2          # not cited, not grounded
    assert flags(LOP, "I'd recommend applying early.", ["S1"]) == [
        "gives advice ('I'd recommend') that no cited source contains"]


def test_invented_codes_numbers_and_remedies():
    text = "You could retake MATH 226 for a 70% or take CPSC 999."
    found = flags(CANT_TELL_221, text)
    assert "mentions CPSC 999, which isn't in the facts" in found
    assert "states 70, which isn't in the facts" in found
    assert "suggests 'retake', which the facts don't mention" in found


def test_clauses_split_and_borrow_listed_codes_only():
    parts = clauses("CPSC 404 lists CPSC 213 and CPEN 212, both of which you can take.", {"CPSC 404"})
    assert parts == [("CPSC 404 lists CPSC 213 and CPEN 212", ["CPSC 404", "CPSC 213", "CPEN 212"]),
                     ("both of which you can take", ["CPSC 213", "CPEN 212"])]


# ---------- enforcement ----------

BAD = ("CPEN 212 is ready: you can take CPEN 212 now.", ["check"])
GOOD = ("You still need CPSC 304.", ["check"])


class Recomposer:
    def __init__(self, result_answer: Answer | None):
        self.result_answer = result_answer
        self.calls: list = []

    def __call__(self, question: str, result: dict, feedback=None, previous=None) -> Answer:
        self.calls.append((feedback, previous))
        assert self.result_answer is not None, "guard should not have recomposed"
        return self.result_answer


def info(out: Answer) -> dict:
    return out.get("guard") or {}


def test_clean_answers_pass_without_a_second_call():
    rc = Recomposer(None)
    out = guard("q", PATH_404, answer(GOOD), rc)
    assert info(out)["action"] == "passed" and rc.calls == []


def test_violations_trigger_one_regeneration_with_feedback():
    rc = Recomposer(answer(GOOD))
    out = guard("q", PATH_404, answer(GOOD, BAD), rc)
    assert info(out)["action"] == "regenerated"
    feedback, previous = rc.calls[0]
    assert "CPEN 212, which isn't ready" in feedback[0] and previous["sentences"][1]["text"] == BAD[0]
    assert info(out)["violations"] == ["2: says the student can take CPEN 212, which isn't ready"]
    assert info(out)["caught"] == [{"sentence": BAD[0],
                                    "why": ["says the student can take CPEN 212, which isn't ready"]}]


def test_persistent_violations_are_trimmed():
    rc = Recomposer(answer(GOOD, BAD))
    out = guard("q", PATH_404, answer(GOOD, BAD), rc)
    assert info(out)["action"] == "trimmed"
    assert [s["text"] for s in out["sentences"]] == [GOOD[0]]
    assert "CPEN 212 now" not in out["text"]


def test_nothing_left_means_the_template_explanation():
    rc = Recomposer(answer(BAD))
    out = guard("q", PATH_404, answer(BAD), rc)
    assert info(out)["action"] == "fallback"
    assert out["composed_by"] == "fallback"
    assert "Required on every route to CPSC 404: CPSC 304." in out["text"]


def test_templates_are_not_checked():
    a = answer(BAD)
    a["composed_by"] = "template"
    assert info(guard("q", PATH_404, a, Recomposer(None)))["action"] == "not needed"


def test_every_message_has_a_kind():
    from agent.guard import violation_kind
    messages = [m for r, t, c in [
        (PATH_404, "You can take CPEN 212. You have completed CPSC 213.", ["check"]),
        (PATH_404, "You haven't completed CPSC 210. So you can take CPSC 404.", ["check"]),
        (CANT_TELL_221, "Retake MATH 226 for 70% or take CPSC 999; I'd recommend it.", ["check"]),
    ] for s in t.split(". ") for m in flags(r, s, c)]
    kinds = {violation_kind(m) for m in messages}
    assert "other" not in kinds
    assert kinds == {"not ready", "invented history", "contradicts history", "contradicts verdict",
                     "invented code", "invented number", "invented remedy", "advice"}


# ---------- from the end-to-end run (1 real, 2 false positives) ----------

def test_e2e_real_overclaim_is_caught():
    path = {**PATH_404, "codes": ["CPSC 340"], "ready_now": ["CPSC 210", "MATH 221"],
            "tree": ["├─ · MATH 221   option", "├─ · MATH 254   option",
                     "├─ · STAT 251   option", "├─ · MATH 318   option", "├─ · CPSC 210   option"]}
    text = ("Several other mathematics options like MATH 221, MATH 254, STAT 251, and MATH 318 "
            "are also available to you now and appear as prerequisites to CPSC 340.")
    assert flags(path, text) == ["says the student can take MATH 254, which isn't ready",
                                 "says the student can take STAT 251, which isn't ready",
                                 "says the student can take MATH 318, which isn't ready"]


def test_e2e_pronoun_claim_about_a_ready_course_is_not_a_verdict_claim():
    ready = {**PATH_404, "ready_now": ["CPSC 304", "CPSC 213"]}
    assert flags(ready, "CPSC 304 is the only course required on every possible route to CPSC 404, "
                        "and you're eligible to take it now based on your completed courses.") == []


def test_e2e_before_you_can_take_is_sequencing_not_availability():
    to_313 = {**PATH_404, "codes": ["CPSC 313"], "title": "Computer Hardware",
              "required_on_every_route": ["CPSC 213", "CPSC 121", "CPSC 210"],
              "ready_now": ["CPSC 210"],
              "tree": ["├─ · CPSC 213   required", "│  ├─ · CPSC 121   required",
                       "│  └─ → CPSC 210   required   ready to take"]}
    assert flags(to_313, "CPSC 121 must also be completed before you can take CPSC 213, "
                         "which itself is a prerequisite for CPSC 313.") == []


def test_e2e_possessive_mention_is_not_an_availability_claim():
    to_340 = {**PATH_404, "codes": ["CPSC 340"],
              "ready_now": ["CPSC 210", "MATH 101", "MATH 103", "MATH 105", "CPSC 203", "MATH 221"],
              "tree": ["├─ · CPSC 221   option", "├─ → CPSC 210   option   ready to take",
                       "├─ → MATH 101   option   ready to take", "├─ → MATH 103   option   ready to take",
                       "├─ → MATH 105   option   ready to take", "├─ → CPSC 203   option   ready to take",
                       "└─ → MATH 221   option   ready to take"]}
    assert flags(to_340, "You can take CPSC 210, MATH 101, MATH 103, MATH 105, CPSC 203, or "
                         "MATH 221 right now as steps toward meeting CPSC 221's prerequisites.") == []


def test_e2e_negated_remedy_states_the_rule(): 
    retake = policy("A student who has passed a course will not be permitted to repeat that "
                    "course for higher standing. Courses on the Science Credit Exclusion Lists "
                    "are considered the same course for this purpose.")
    assert flags(retake, "If you have already passed one course from a credit exclusion list, you "
                         "cannot repeat the other course for a higher grade, since courses in the "
                         "Science Credit Exclusion Lists are treated as the same course.",
                 ["S1"]) == []
    # An actual suggestion is still caught.
    assert flags(retake, "You could repeat it for a higher grade next year.", ["S1"]) == [
        "suggests 'higher grade', which the facts don't mention"]


def test_e2e_claiming_the_calendar_is_silent_is_caught():
    corpus = policy("First-year students may register in a maximum of 38 credits.")
    bad = ("The calendar does not specify a cap on how many first-year courses count toward "
           "the degree.")
    assert flags(corpus, bad, ["S1"]) == [
        "claims the calendar is silent; only the retrieved sections can be checked"]
    ok = "The sections I found don't mention a cap on first-year courses."
    assert flags(corpus, ok, ["S1"]) == []


def test_leading_list():
    from agent.guard import leading_list
    assert leading_list(" either CPSC 221 or DSCI 221 right now") == ["CPSC 221", "DSCI 221"]
    assert leading_list(" CPSC 213 now since you've finished CPSC 210") == ["CPSC 213"]
    assert leading_list(" nothing here") == []


def test_neither_of_which_is_a_negative_history_claim():
    assert flags(PATH_404, "Before CPSC 404, you need CPSC 304 and CPSC 213, "
                           "neither of which you've completed.") == []
    assert flags(PATH_404, "You need CPSC 210 and CPSC 304, neither of which you've completed.") == [
        "says the student hasn't completed CPSC 210, but they have"]