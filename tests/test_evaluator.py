"""The tri-state combination rules, as executable specification."""

import pytest

from core.evaluator import INDETERMINATE, NOT_SATISFIED, SATISFIED, evaluate
from core.transcript import Transcript

C = lambda code: {"op": "COURSE", "code": code, "tracked": True}
UNPARSED = {"op": "UNPARSED", "text": "something we could not structure"}
PERMISSION = {"op": "PERMISSION", "note": "permission of the department"}


def st(spec="", year=None, programs=None):
    return Transcript.parse(spec, year=year, programs=programs)


# ---------- leaves ----------

def test_course_present():
    assert evaluate(C("CPSC 110"), st("CPSC 110")).state is SATISFIED

def test_course_absent():
    assert evaluate(C("CPSC 110"), st("CPSC 121")).state is NOT_SATISFIED

def test_permission_is_always_indeterminate():
    r = evaluate(PERMISSION, st("CPSC 110"))
    assert r.state is INDETERMINATE
    assert r.headline  # exercises Reason unwrapping

def test_unparsed_is_always_indeterminate():
    assert evaluate(UNPARSED, st("CPSC 110")).state is INDETERMINATE


# ---------- ALL_OF ----------

def test_all_of_every_child_satisfied():
    tree = {"op": "ALL_OF", "children": [C("CPSC 110"), C("CPSC 121")]}
    assert evaluate(tree, st("CPSC 110, CPSC 121")).state is SATISFIED

def test_all_of_one_missing_fails():
    tree = {"op": "ALL_OF", "children": [C("CPSC 110"), C("CPSC 121")]}
    assert evaluate(tree, st("CPSC 110")).state is NOT_SATISFIED

def test_all_of_definite_failure_beats_uncertainty():
    """A provably unmet requirement is NOT_SATISFIED even alongside unknowns."""
    tree = {"op": "ALL_OF", "children": [C("CPSC 999"), UNPARSED]}
    assert evaluate(tree, st("CPSC 110")).state is NOT_SATISFIED

def test_all_of_uncertainty_propagates():
    tree = {"op": "ALL_OF", "children": [C("CPSC 110"), PERMISSION]}
    assert evaluate(tree, st("CPSC 110")).state is INDETERMINATE


# ---------- ONE_OF ----------

def test_one_of_any_satisfied():
    tree = {"op": "ONE_OF", "children": [C("CPSC 110"), C("CPSC 121")]}
    assert evaluate(tree, st("CPSC 121")).state is SATISFIED

def test_one_of_satisfied_short_circuits_past_unknowns():
    """THE asymmetry: a met branch makes other branches irrelevant."""
    tree = {"op": "ONE_OF", "children": [C("CPSC 110"), PERMISSION]}
    assert evaluate(tree, st("CPSC 110")).state is SATISFIED

def test_one_of_unknown_survives_when_nothing_satisfies():
    tree = {"op": "ONE_OF", "children": [C("CPSC 999"), PERMISSION]}
    assert evaluate(tree, st("CPSC 110")).state is INDETERMINATE

def test_one_of_all_absent():
    tree = {"op": "ONE_OF", "children": [C("CPSC 998"), C("CPSC 999")]}
    assert evaluate(tree, st("CPSC 110")).state is NOT_SATISFIED


# ---------- MIN_GRADE ----------

def test_min_grade_met():
    tree = {"op": "MIN_GRADE", "percent": 68, "child": C("MATH 226")}
    assert evaluate(tree, st("MATH 226:74")).state is SATISFIED

def test_min_grade_not_met():
    tree = {"op": "MIN_GRADE", "percent": 68, "child": C("MATH 226")}
    assert evaluate(tree, st("MATH 226:61")).state is NOT_SATISFIED

def test_min_grade_unknown_grade_is_indeterminate():
    """Took the course, grade not reported. Do not assume."""
    tree = {"op": "MIN_GRADE", "percent": 68, "child": C("MATH 226")}
    assert evaluate(tree, st("MATH 226")).state is INDETERMINATE

def test_min_grade_course_absent_fails():
    tree = {"op": "MIN_GRADE", "percent": 68, "child": C("MATH 226")}
    assert evaluate(tree, st("MATH 200")).state is NOT_SATISFIED

def test_min_grade_distributes_over_one_of():
    tree = {"op": "MIN_GRADE", "percent": 65,
            "child": {"op": "ONE_OF", "children": [C("MATH 302"), C("STAT 302")]}}
    assert evaluate(tree, st("STAT 302:70")).state is SATISFIED
    assert evaluate(tree, st("STAT 302:60")).state is NOT_SATISFIED


# ---------- STANDING / PROGRAM ----------

def test_standing_met_and_exceeded():
    tree = {"op": "STANDING", "year": 3}
    assert evaluate(tree, st(year=3)).state is SATISFIED
    assert evaluate(tree, st(year=4)).state is SATISFIED

def test_standing_not_met():
    assert evaluate({"op": "STANDING", "year": 3}, st(year=2)).state is NOT_SATISFIED

def test_standing_unknown_year():
    assert evaluate({"op": "STANDING", "year": 3}, st()).state is INDETERMINATE

def test_program_match_is_case_insensitive():
    tree = {"op": "PROGRAM", "name": "Computer Science"}
    assert evaluate(tree, st(programs={"computer science"})).state is SATISFIED

def test_program_unknown():
    assert evaluate({"op": "PROGRAM", "name": "Statistics"}, st()).state is INDETERMINATE


# ---------- untracked courses ----------

def test_untracked_course_accepted_when_reported():
    tree = {"op": "COURSE", "code": "PSYC 218", "tracked": False}
    assert evaluate(tree, st("PSYC 218")).state is SATISFIED

def test_untracked_course_absent_is_indeterminate():
    """We do not hold this course, so absence is not evidence of absence."""
    tree = {"op": "COURSE", "code": "PSYC 218", "tracked": False}
    assert evaluate(tree, st("CPSC 110")).state is INDETERMINATE


# ---------- real trees ----------

def test_cpsc_221_via_grade_branch():
    tree = {"op": "ALL_OF", "children": [
        {"op": "ONE_OF", "children": [C("CPSC 210"), C("CPEN 221")]},
        {"op": "ONE_OF", "children": [
            {"op": "ONE_OF", "children": [
                C("CPSC 121"), C("MATH 220"),
                {"op": "OUT_OF_SCOPE", "code": "MATH_O 220", "reason": "okanagan"}]},
            {"op": "MIN_GRADE", "percent": 68, "child": C("MATH 226")}]}]}
    assert evaluate(tree, st("CPSC 210, MATH 226:74")).state is SATISFIED
    # 61% fails the grade branch, but MATH_O 220 (Okanagan) is unverifiable,
    # so the ONE_OF cannot conclude NOT_SATISFIED.
    assert evaluate(tree, st("CPSC 210, MATH 226:61")).state is INDETERMINATE
    assert evaluate(tree, st("CPSC 210, CPSC 121")).state is SATISFIED


def test_trace_names_the_failing_node():
    tree = {"op": "ALL_OF", "children": [C("CPSC 110"), C("CPSC 121")]}
    result = evaluate(tree, st("CPSC 110"))
    assert any("CPSC 121" in r.text for r in result.reasons)