"""Facts, verdict sentences, templates, and rendering. No LLM."""

from agent.present import (
    CHECK,
    DISCLAIMER,
    YOU,
    Sentence,
    build_facts,
    headline,
    plain_answer,
    render,
    template_answer,
)

CTX = {"completed": ["CPSC 210"], "in_progress": [], "grades": {"MATH 226": "68–71%"},
       "year": None, "programs": [], "transcript_given": True,
       "assumptions": ["read '221' as CPSC 221"], "ignored": []}


def course(verdict="SATISFIED", reasons=None, **kw):
    return {"code": "CPSC 221", "found": True, "title": "Basic Algorithms",
            "prereq_text": "One of CPSC_V 210, CPEN_V 221 ...", "extraction_status": "parsed",
            "source_url": "https://cal/cpscv-221", "verdict": verdict,
            "summary": "CPSC 210: completed",
            "reasons": reasons or [{"state": verdict, "text": "CPSC 210: completed"}], **kw}


def evaluated(*courses):
    return {"kind": "eligibility", "status": "evaluated", "codes": ["CPSC 221"],
            "context": CTX, "courses": list(courses)}


POLICY = {"kind": "policy", "status": "ok", "codes": [], "hits": [
    {"section_path": "B.Sc. > Course Approval > Repeating", "source_url": "https://cal/approval",
     "score": 0.6, "content": "B.Sc. > Course Approval > Repeating\n\nA passed course may not be repeated."},
    {"section_path": "B.Sc. > Registration", "source_url": "https://cal/registration",
     "score": 0.5, "content": "B.Sc. > Registration\n\nCorequisites are taken concurrently."},
]}


# ---------- facts ----------

def test_eligibility_facts_have_you_check_and_a_source():
    f = build_facts("can I take 221?", evaluated(course()))
    assert f.ids == {YOU, CHECK, "S1"}
    assert [(x["id"], x["label"], x["url"]) for x in f.sources] == [
        ("S1", "CPSC 221 — Basic Algorithms", "https://cal/cpscv-221")]
    assert f.sources[0]["text"].startswith("Prerequisites as written in the calendar")
    assert "read '221' as CPSC 221" in f.text
    assert "CPSC 221: SATISFIED" in f.text
    assert "One of CPSC_V 210" in f.text


def test_policy_facts_are_numbered_sources_without_the_path_prefix_in_the_body():
    f = build_facts("retake?", POLICY)
    assert f.ids == {"S1", "S2"}
    assert "[S1] B.Sc. > Course Approval > Repeating\nA passed course may not be repeated." in f.text


def test_long_sources_are_truncated():
    long = dict(POLICY, hits=[dict(POLICY["hits"][0], content="x\n\n" + "y" * 5000)])
    assert "y" * 1500 + " …" in build_facts("q", long).text


def test_question_is_marked_as_not_a_source():
    assert "QUESTION (for context only — not a source)" in build_facts("q", POLICY).text


# ---------- verdict sentences ----------

def test_headline_per_verdict():
    for verdict, start in [("SATISFIED", "Yes"), ("NOT_SATISFIED", "Not yet"),
                           ("INDETERMINATE", "I can't tell"), ("NO_PREREQUISITES", "CPSC 221 has no")]:
        assert headline(evaluated(course(verdict)))[0].startswith(start)


def test_headline_is_empty_for_policy():
    assert headline(POLICY) == []


def test_sweep_and_unlock_headlines_count_correctly():
    sweep = {"kind": "eligibility", "status": "sweep", "subjects": ["CPSC"],
             "counts": {"eligible": 1, "no_prereq": 0, "to_confirm": 0, "not_yet": 3},
             "eligible": ["CPSC 210"], "no_prereq": [], "to_confirm": []}
    assert headline(sweep) == [("Based on what you've told me, you meet the listed "
                               "prerequisites for 1 course in CPSC.")]
    unlock = {"kind": "unlock", "status": "personal", "codes": ["CPSC 221"],
              "newly_eligible": ["CPSC 304", "CPSC 310"]}
    assert headline(unlock) == ["Taking CPSC 221 opens 2 courses for you."]


# ---------- templates and fallback ----------

def test_templates_cover_every_no_llm_status():
    for result in [
        {"status": "needs_course"},
        {"status": "course_not_found", "codes": ["CPSC 999"]},
        {"status": "needs_clarification", "message": "'320' could be CPSC 320, MATH 320. Which?"},
        {"status": "refused", "message": "No advice.", "examples": ["a", "b"]},
        {"status": "error", "message": "boom"},
        {"status": "no_results"},
    ]:
        assert template_answer(result), result


def test_error_template_does_not_leak_the_internal_message():
    assert "boom" not in template_answer({"status": "error", "message": "boom"})[0].text


def test_plain_answer_cites_only_known_ids():
    for result in [evaluated(course("NOT_SATISFIED")), POLICY]:
        f = build_facts("q", result)
        body = plain_answer(result, f)
        assert body
        assert all(c in f.ids for s in body for c in s.cites)


# ---------- rendering ----------

def test_render_numbers_sources_by_first_use_and_adds_footer():
    f = build_facts("q", POLICY)
    text, used = render([], [Sentence("B.", ["S2"]), Sentence("A.", ["S1", "S2"]),
                             Sentence("C.", [CHECK])], f)
    assert text.startswith("B. [1] A. [2][1] C.")
    assert [u["id"] for u in used] == ["S2", "S1"]
    assert "[1] B.Sc. > Registration — https://cal/registration" in text
    assert text.endswith(DISCLAIMER)


def test_render_puts_the_lead_first_without_markers():
    f = build_facts("q", evaluated(course()))
    text, used = render(["Yes."], [Sentence("Because.", [YOU])], f)
    assert text.startswith("Yes. Because.")
    assert used == [] and "Sources:" not in text


# ---------- from the first real answers ----------

CANT_TELL_REASONS = [
    {"state": "SATISFIED", "text": "CPSC 210: completed"},
    {"state": "NOT_SATISFIED", "text": "CPSC 121: not completed"},
    {"state": "INDETERMINATE", "text": "MATH_O 220: Okanagan course, outside our data"},
    {"state": "NOT_SATISFIED", "text": "MATH 226: 61% < 68% required"},
]


def test_cant_tell_headline_names_what_cant_be_checked():
    lead = headline(evaluated(course("INDETERMINATE", CANT_TELL_REASONS)))
    assert lead[1] == "What I can't check: MATH_O 220: Okanagan course, outside our data."


def test_cant_tell_facts_mark_unknowns_as_not_missing():
    f = build_facts("q", evaluated(course("INDETERMINATE", CANT_TELL_REASONS)))
    assert "can't be checked — unknown, not missing: MATH_O 220" in f.text


def test_citing_check_points_to_the_page_it_was_computed_from():
    f = build_facts("q", evaluated(course("NOT_SATISFIED")))
    text, used = render([], [Sentence("CPSC 121 is missing.", [CHECK])], f)
    assert text.startswith("CPSC 121 is missing. [1]")
    assert used[0]["url"] == "https://cal/cpscv-221"


def test_unlock_answers_get_a_source_even_when_only_check_is_cited():
    unlock = {"kind": "unlock", "status": "personal", "codes": ["CPSC 221"], "context": CTX,
              "title": "Basic Algorithms", "source_url": "https://cal/cpscv-221",
              "newly_eligible": ["CPSC 304"], "to_confirm": [], "still_blocked": [],
              "already_eligible": []}
    f = build_facts("q", unlock)
    text, _ = render([], [Sentence("CPSC 304 opens up.", [CHECK, YOU])], f)
    assert "Sources:\n[1] CPSC 221 — Basic Algorithms" in text


def test_refusal_examples_are_quoted():
    body = template_answer({"status": "refused", "message": "No.",
                            "examples": ["Can I take A?", "What does B unlock?", "Can I retake C?"]})
    assert body[1].text == ('You could ask things like "Can I take A?", '
                            '"What does B unlock?", or "Can I retake C?"')


def test_unlock_headline_says_finishing_when_they_already_have_the_course():
    unlock = {"kind": "unlock", "status": "personal", "codes": ["CPSC 213"],
              "newly_eligible": ["CPSC 310", "CPSC 313", "CPSC 317"]}
    assert headline(unlock) == ["Taking CPSC 213 opens 3 courses for you."]
    assert headline({**unlock, "already_taken": True}) == ["Finishing CPSC 213 opens 3 courses for you."]
