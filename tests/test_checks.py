from agent.checks import (
    advice_phrases,
    drift,
    ungrounded_codes,
    ungrounded_numbers,
    ungrounded_remedies,
    verdict_conflicts,
)


def test_advice_phrases():
    assert advice_phrases("You should take CPSC 213 first.") == ["You should"]
    assert advice_phrases("I'd recommend it. Consider taking MATH 200.") == ["I'd recommend",
                                                                             "Consider taking"]
    assert advice_phrases("CPSC 213 is the best option.") == ["the best option"]
    assert advice_phrases("You still need CPSC 213.") == []


def test_ungrounded_codes_catches_codes_and_bare_numbers():
    facts = "CPSC 221 requires CPSC 210 and one of CPSC 121, MATH 220."
    assert ungrounded_codes("You need CPSC 210 and CPSC 213.", facts) == ["CPSC 213"]
    assert ungrounded_codes("Then take 310.", facts) == ["310"]
    assert ungrounded_codes("CPSC 121 or 220 works.", facts) == []


def test_ungrounded_numbers():
    facts = "MATH 226: 61% < 68% required. At most 6 credits."
    assert ungrounded_numbers("You got 61%, below 68%.", facts) == []
    assert ungrounded_numbers("You need 70% or 9 credits.", facts) == ["70", "9"]


def test_verdict_conflicts():
    indet = {"kind": "eligibility", "codes": ["CPSC 221"], "courses": [{"verdict": "INDETERMINATE"}]}
    assert verdict_conflicts(indet, "So you can take CPSC 221.")
    assert verdict_conflicts(indet, "You don't meet one requirement.")
    assert verdict_conflicts(indet, "The MATH 226 grade isn't enough on its own.") == []
    ok = {"kind": "eligibility", "courses": [{"verdict": "SATISFIED"}]}
    assert verdict_conflicts(ok, "You meet both requirements.") == []
    assert verdict_conflicts({"kind": "policy"}, "You can take it.") == []


def test_drift_bundles_all_checks():
    d = drift({"kind": "policy"}, "facts", "You should take CPSC 999.")
    assert d["advice"] and d["ungrounded_codes"] == ["CPSC 999"]


# ---------- from the first real answers ----------

CANT_TELL = ("You would need to either complete one of the missing courses (CPSC 121, MATH 220, "
             "or MATH_O 220) or retake MATH 226 and achieve at least 68% to satisfy the prerequisites.")
CANT_TELL_FACTS = "CPSC 221: INDETERMINATE ... MATH 226: 61% < 68% required ... MATH_O 220"


def test_invented_remedy_is_caught():
    assert advice_phrases(CANT_TELL) == ["You would need to either complete"]
    assert ungrounded_remedies(CANT_TELL, CANT_TELL_FACTS) == ["retake"]


def test_remedy_words_are_fine_when_the_facts_discuss_them():
    facts = "A student who has passed a course will not be permitted to repeat that course."
    assert ungrounded_remedies("Passed courses can't be repeated for higher standing.", facts) == []


def test_referral_to_an_advisor_is_flagged():
    text = "You should consult with academic advisors in the relevant department."
    assert advice_phrases(text) == ["You should", "consult with academic advis"]


def test_conflicts_ignore_true_claims_about_other_courses():
    path = {"kind": "path", "codes": ["CPSC 404"], "verdict": "NOT_SATISFIED"}
    ok = "You can take CPSC 221 and CPSC 213 now, and you're eligible for them."
    assert verdict_conflicts(path, ok) == []
    assert verdict_conflicts(path, "You can take CPSC 404 now.") == ["claims eligibility: 'You can take'"]
    assert verdict_conflicts(path, "So you're eligible.") == ["claims eligibility: 'you're eligible'"]


def test_conflict_from_the_real_cant_tell_answer_is_caught():
    indet = {"kind": "eligibility", "codes": ["CPSC 221"],
             "courses": [{"code": "CPSC 221", "verdict": "INDETERMINATE"}]}
    body = ("You don't meet the stated prerequisites for CPSC 221 because your MATH 226 "
            "score of 61% falls below the required 68%.")
    assert verdict_conflicts(indet, body) == ["claims ineligibility: 'You don't meet'"]
