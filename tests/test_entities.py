"""Entity validation tests. The LLM is faked; every rule about what to
believe is deterministic and tested here."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from agent import entities as ent
from agent.entities import EntityError, extract, to_transcript, validate
from core.codes import find_codes

CATALOGUE = {"CPSC 110", "CPSC 121", "CPSC 210", "CPSC 213", "CPSC 221",
             "CPSC 320", "MATH 320", "MATH 200", "MATH 226"}
PROGRAMS = {"Computer Science", "Statistics"}


def C(code, written=None):
    return {"code": code, "as_written": written or code}


def G(code, written=None, grade="", grade_written=""):
    return {**C(code, written), "grade": grade, "grade_as_written": grade_written}


def raw(**kw):
    base = {"targets": [], "completed": [], "in_progress": [], "year": 0,
            "program": "", "no_courses_yet": False}
    return {**base, **kw}


def v(question, **kw):
    return validate(raw(**kw), question, CATALOGUE, PROGRAMS)


# ---------- grounding ----------

def test_full_codes_pass_through():
    e = v("Can I take CPSC 221 with CPSC 210?", targets=[C("CPSC 221")], completed=[G("CPSC 210")])
    assert e["targets"] == ["CPSC 221"] and e["completed"] == ["CPSC 210"]
    assert e["transcript_given"] and not e["assumptions"] and not e["rejected"]


def test_code_not_in_the_question_is_rejected():
    e = v("Can I take CPSC 221?", targets=[C("CPSC 221")], completed=[G("CPSC 213")])
    assert e["completed"] == []
    assert "CPSC 213 is not in the question" in e["rejected"][0]


def test_as_written_must_contain_the_number():
    e = v("Can I take CPSC 221?", targets=[C("CPSC 210", "CPSC 221")])
    assert e["targets"] == [] and e["rejected"]


def test_subject_carried_from_context_is_accepted_and_said_out_loud():
    e = v("I did CPSC 110 and 121. Can I take 210?",
          targets=[C("CPSC 210", "210")], completed=[G("CPSC 110"), G("CPSC 121", "121")])
    assert e["targets"] == ["CPSC 210"]
    assert "read '210' as CPSC 210" in e["assumptions"]


def test_subject_alias_counts_as_written():
    e = v("Can a CS student take 221?", targets=[C("CPSC 221", "221")])
    assert e["targets"] == ["CPSC 221"]


def test_invented_subject_falls_back_to_the_catalogue():
    # No MATH anywhere in the question: "MATH" is the model's guess.
    e = v("can I take 226?", targets=[C("MATH 226", "226")])
    assert e["targets"] == ["MATH 226"]
    assert "the only course with that number" in e["assumptions"][0]


def test_bare_number_with_several_courses_is_ambiguous():
    e = v("can I take 320?", targets=[C("? 320", "320")])
    assert e["targets"] == []
    assert e["ambiguous"] == [{"as_written": "320", "role": "target",
                               "candidates": ["CPSC 320", "MATH 320"]}]


def test_bare_number_matching_nothing_is_rejected():
    e = v("can I take 999?", targets=[C("? 999", "999")])
    assert e["targets"] == [] and "no course numbered 999" in e["rejected"][0]


def test_campus_suffix_is_dropped():
    e = v("Could I take CPSC_V 221?", targets=[C("CPSC 221", "CPSC_V 221")])
    assert e["targets"] == ["CPSC 221"]


@pytest.mark.parametrize("code", ["MATH_O 200", "MATH 200"])
def test_okanagan_courses_are_rejected_even_if_the_suffix_was_dropped(code):
    e = v("I took MATH_O 200.", completed=[G(code, "MATH_O 200")])
    assert e["completed"] == [] and "Okanagan" in e["rejected"][0]


def test_unreadable_code_is_rejected():
    e = v("Can I take calculus?", targets=[C("calculus")])
    assert e["targets"] == [] and "unreadable" in e["rejected"][0]


# ---------- grades ----------

def test_percentage_grade():
    e = v("I got 74 in MATH 226", completed=[G("MATH 226", grade="74", grade_written="74")])
    assert e["grades"] == {"MATH 226": 74}


def test_letter_grade_becomes_a_range():
    e = v("got a B- in MATH 226", completed=[G("MATH 226", grade="B-", grade_written="a B-")])
    assert e["grade_ranges"] == {"MATH 226": [68, 71]}
    assert to_transcript(e).grade_range("MATH 226") == (68, 71)


def test_grade_not_in_the_question_is_dropped_but_course_kept():
    e = v("I passed MATH 226", completed=[G("MATH 226", grade="90", grade_written="90")])
    assert e["completed"] == ["MATH 226"] and e["grades"] == {}
    assert "not in the question" in e["rejected"][0]


@pytest.mark.parametrize("grade", ["45", "F"])
def test_failing_grade_means_not_completed(grade):
    e = v(f"I got {grade} in MATH 226", completed=[G("MATH 226", grade=grade, grade_written=grade)])
    assert e["completed"] == [] and "isn't counted" in e["assumptions"][0]
    assert e["transcript_given"]      # a failed course is still history


# ---------- year, program, in progress ----------

@pytest.mark.parametrize("question", ["I'm in second year", "2nd-year student", "year 2 here"])
def test_year_is_accepted_when_written(question):
    assert v(question, year=2)["year"] == 2


def test_year_not_written_is_rejected():
    e = v("Can I take CPSC 221?", year=3)
    assert e["year"] is None and "year 3" in e["rejected"][0]


def test_program_matched_to_known_names():
    assert v("I'm a CS major", program="CS major")["programs"] == ["Computer Science"]
    assert v("I'm in Statistics", program="Statistics")["programs"] == ["Statistics"]
    assert v("I'm in Biology", program="Biology")["programs"] == []


def test_in_progress_counts_toward_the_transcript_with_a_note():
    e = v("I'm taking CPSC 210 now", in_progress=[C("CPSC 210")])
    assert e["transcript_given"]
    assert to_transcript(e).completed == {"CPSC 210"}
    assert "in progress" in e["assumptions"][0]


def test_no_courses_yet_is_a_transcript():
    assert v("I haven't taken anything", no_courses_yet=True)["transcript_given"]


def test_nothing_said_about_history_is_not_a_transcript():
    assert not v("Can I take CPSC 221?", targets=[C("CPSC 221")])["transcript_given"]


def test_codes_mentioned_but_not_extracted_are_reported():
    e = v("Can I take CPSC 221 with CPSC 210?", targets=[C("CPSC 221")])
    assert e["unused"] == ["CPSC 210"]


# ---------- the LLM call ----------

class FakeClient:
    def __init__(self, text, stop_reason="end_turn"):
        self.text, self.stop_reason, self.calls = text, stop_reason, []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        blocks = [SimpleNamespace(type="text", text=self.text)] if self.text else []
        return SimpleNamespace(content=blocks, stop_reason=self.stop_reason)


def test_extract_calls_the_model_then_validates():
    fake = FakeClient(json.dumps(raw(targets=[C("CPSC 221")], completed=[G("CPSC 999")])))
    e = extract("Can I take CPSC 221?", client=fake, cat=CATALOGUE, programs=PROGRAMS)
    assert e["targets"] == ["CPSC 221"] and e["completed"] == []
    call = fake.calls[0]
    assert call["model"] == ent.ENTITY_MODEL
    assert call["output_config"]["format"]["schema"] == ent.ENTITY_SCHEMA


@pytest.mark.parametrize("text,match", [("", "no text"), ("nope", "not JSON"), ("[1]", "not an object")])
def test_extract_errors(text, match):
    with pytest.raises(EntityError, match=match):
        extract("q", client=FakeClient(text), cat=CATALOGUE, programs=PROGRAMS)


def test_prompt_examples_do_not_leak_eval_questions():
    root = Path(__file__).parents[1] / "eval"
    questions = [q for f in ("entities_questions.yaml", "entities_holdout.yaml")
                 for q in yaml.safe_load((root / f).read_text())]
    eval_codes = {c for q in questions for c in find_codes(q["question"])}
    prompt_codes = set(find_codes(ent.SYSTEM_PROMPT))
    assert prompt_codes and not (prompt_codes & eval_codes)


def test_eval_comparison_maps_letter_ranges_back_to_letters():
    from eval.run_entities_eval import actual_of, expected_of, extra_codes
    e = v("got a B- in MATH 226 and 80 in CPSC 110, can I take CPSC 221",
          targets=[C("CPSC 221")],
          completed=[G("MATH 226", grade="B-", grade_written="a B-"),
                     G("CPSC 110", grade="80", grade_written="80")])
    q = {"targets": ["CPSC 221"], "completed": {"MATH 226": "B-", "CPSC 110": 80}}
    assert expected_of(q) == actual_of(e)
    assert extra_codes(expected_of({"targets": ["CPSC 221"]}), actual_of(e)) == {"MATH 226", "CPSC 110"}


# ---------- regression: expanded as_written (eval: unlock-with-history) ----------

LIST_Q = "What does CPSC 213 unlock for me? I've passed CPSC 110, 121, 210 and 213."


def test_model_expanding_a_bare_number_is_still_grounded():
    """The model wrote as_written "CPSC 121" for a bare "121". The number is in
    the question, continuing a CPSC list, so the course is real."""
    e = v(LIST_Q, targets=[C("CPSC 213")],
          completed=[G("CPSC 110"), G("CPSC 121"), G("CPSC 210"), G("CPSC 213")])
    assert e["completed"] == ["CPSC 110", "CPSC 121", "CPSC 210", "CPSC 213"]
    assert e["rejected"] == []
    assert "read '121' as CPSC 121" in e["assumptions"]


def test_a_number_written_with_another_subject_cannot_be_borrowed():
    # 200 appears only as MATH 200, so an invented CPSC 200 is rejected.
    e = v("I did MATH 200. Can I take CPSC 210?",
          targets=[C("CPSC 210")], completed=[G("MATH 200"), G("CPSC 200")])
    assert e["completed"] == ["MATH 200"]
    assert "CPSC 200 is not in the question" in e["rejected"][0]


def test_a_percentage_is_not_a_course_number():
    e = v("I got 100% in MATH 101. Can I take MATH 200?",
          targets=[C("MATH 200")], completed=[G("MATH 101"), G("MATH 100")])
    assert e["completed"] == ["MATH 101"]
    assert "MATH 100 is not in the question" in e["rejected"][0]


def test_occurrences_reads_subjects_and_skips_connectives():
    from agent.entities import _occurrences
    assert _occurrences("121", LIST_Q) == [(None, None)]
    assert _occurrences("213", LIST_Q) == [("CPSC", None), (None, None)]
    assert _occurrences("220", "took MATH_O 220 and cpsc 220") == [("MATH", "_O"), ("CPSC", None)]


# ---------- safety net: the model leaves out the target ----------

def test_single_unused_code_becomes_the_target():
    from agent.entities import fill_missing_target
    e = v("Which courses need MATH 200? I haven't taken it yet.")      # model extracted nothing
    assert e["unused"] == ["MATH 200"]
    filled = fill_missing_target(e, "unlock")
    assert filled["targets"] == ["MATH 200"] and filled["unused"] == []
    assert "took MATH 200 as the course you're asking about" in filled["assumptions"]
    assert e["targets"] == []                                          # original untouched


def test_no_fill_when_it_would_be_a_guess():
    from agent.entities import fill_missing_target
    two = v("Do CPSC 210 or CPSC 221 lead anywhere?")
    assert fill_missing_target(two, "unlock")["targets"] == []          # which one?
    sweep = v("What can I take? I've done CPSC 110. Also CPSC 121?",
              completed=[G("CPSC 110")])
    assert fill_missing_target(sweep, "eligibility")["targets"] == []   # a sweep
    have = v("Can I take CPSC 221?", targets=[C("CPSC 221")])
    assert fill_missing_target(have, "path") is have                    # nothing missing
