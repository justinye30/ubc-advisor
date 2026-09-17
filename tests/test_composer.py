"""Composer tests with a scripted fake model."""

import json
from types import SimpleNamespace

import anthropic
import httpx2

from agent import composer
from agent.composer import compose, structural_problems
from agent.present import Facts, Sentence

POLICY = {"kind": "policy", "status": "ok", "codes": [], "hits": [
    {"section_path": "B.Sc. > Repeating", "source_url": "https://cal/a", "score": 0.6,
     "content": "B.Sc. > Repeating\n\nA passed course may not be repeated for higher standing."}]}
ELIG = {"kind": "eligibility", "status": "evaluated", "codes": ["CPSC 221"],
        "context": {"completed": ["CPSC 210"], "in_progress": [], "grades": {}, "year": None,
                    "programs": [], "transcript_given": True, "assumptions": [], "ignored": []},
        "courses": [{"code": "CPSC 221", "found": True, "title": "Algorithms",
                     "prereq_text": "...", "extraction_status": "parsed",
                     "source_url": "https://cal/221", "verdict": "NOT_SATISFIED",
                     "summary": "CPSC 121: not completed",
                     "reasons": [{"state": "NOT_SATISFIED", "text": "CPSC 121: not completed"}]}]}


class Script:
    """Returns each reply in turn; an Exception instance is raised instead."""
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)],
                               stop_reason="end_turn")


def say(*sentences):
    return json.dumps({"sentences": [{"text": t, "cites": c} for t, c in sentences]})


def test_valid_answer_is_used():
    fake = Script(say(("Passed courses can't be repeated for a higher mark.", ["S1"])))
    a = compose("Can I retake a course I passed?", POLICY, client=fake)
    assert a["composed_by"] == "llm"
    assert a["text"].startswith("Passed courses can't be repeated for a higher mark. [1]")
    assert a["sources"][0]["url"] == "https://cal/a"


def test_request_carries_facts_outcome_and_schema():
    fake = Script(say(("CPSC 121 is missing.", ["check"])))
    compose("can I take 221?", ELIG, client=fake)
    call = fake.calls[0]
    content = call["messages"][0]["content"]
    assert "OUTCOME (already written)\nNot yet" in content
    assert "CITABLE IDS: S1, check, you" in content
    assert call["output_config"]["format"]["schema"] == composer.ANSWER_SCHEMA


def test_verdict_sentence_is_never_written_by_the_model():
    fake = Script(say(("CPSC 121 is missing.", ["check"])))
    a = compose("q", ELIG, client=fake)
    assert a["lead"] == [("Not yet — based on what you've told me, you don't meet the "
                         "listed prerequisites for CPSC 221.")]
    assert a["text"].startswith(a["lead"][0])


def test_bad_citation_is_retried_with_the_rejected_answer_shown():
    bad = say(("Something.", ["S9"]))
    fake = Script(bad, say(("CPSC 121 is missing.", ["check"])))
    a = compose("q", ELIG, client=fake)
    assert a["composed_by"] == "llm"
    retry = fake.calls[1]["messages"]
    assert retry[1] == {"role": "assistant", "content": bad}
    assert "unknown ids ['S9']" in retry[2]["content"]
    assert a["problems"] == ["sentence 1 cites unknown ids ['S9']"]


def test_two_failures_fall_back_to_the_template_explanation():
    fake = Script("not json", say(("Uncited.", [])))
    a = compose("q", ELIG, client=fake)
    assert a["composed_by"] == "fallback"
    assert "For CPSC 221: CPSC 121: not completed." in a["text"]
    assert len(a["problems"]) == 2


def test_api_errors_fall_back():
    err = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))
    a = compose("q", POLICY, client=Script(err, err))
    assert a["composed_by"] == "fallback"
    assert "most relevant" in a["text"]


def test_templates_never_call_the_model():
    fake = Script()
    for result in [{"kind": "out_of_scope", "status": "refused", "message": "No.", "examples": ["x"]},
                   {"kind": "error", "status": "error", "message": "x"},
                   {"kind": "eligibility", "status": "needs_clarification", "message": "Which?"},
                   {"kind": "policy", "status": "no_results", "hits": []}]:
        assert compose("q", result, client=fake)["composed_by"] == "template"
    assert fake.calls == []


def test_structural_problems():
    facts = Facts(text="", ids={"S1", "check"})
    assert structural_problems([], facts) == ["no sentences"]
    assert structural_problems([Sentence(" ", ["S1"])], facts) == ["sentence 1 is empty"]
    too_many = [Sentence("x", ["S1"])] * (composer.MAX_SENTENCES + 1)
    assert "limit" in structural_problems(too_many, facts)[0]
