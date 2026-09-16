"""Pure parts of retrieval and its eval: code matching, fusion, scoring."""

from core.retrieval import Hit, code_tsquery, rrf
from eval.run_retrieval_eval import first_rank, matches, summarize

SUBJECTS = {"CPSC", "MATH", "STAT", "COMM"}


def test_code_tsquery_extracts_known_subjects():
    assert code_tsquery("Can STAT 251 replace math200?", SUBJECTS) == "(stat & 251) | (math & 200)"


def test_code_tsquery_ignores_words_that_look_like_codes():
    assert code_tsquery("Do I need to take 300 level courses?", SUBJECTS) is None


def test_code_tsquery_handles_campus_suffix_and_letters():
    assert code_tsquery("cpsc_v 110 and MATH 100a", SUBJECTS) == "(cpsc & 110) | (math & 100a)"


def test_code_tsquery_dedupes():
    assert code_tsquery("COMM 337 or comm 337?", SUBJECTS) == "(comm & 337)"


def test_code_tsquery_ignores_four_digit_numbers():
    assert code_tsquery("the 2026 calendar", SUBJECTS) is None


def test_rrf_rewards_agreement():
    fused = rrf([[1, 2, 3], [3, 4]])
    assert fused[0][0] == 3           # in both lists beats rank 1 in one list
    assert {cid for cid, _ in fused} == {1, 2, 3, 4}


def test_rrf_single_list_preserves_order():
    assert [cid for cid, _ in rrf([[5, 2, 9]])] == [5, 2, 9]


URL = "https://x/faculty-science/bachelor-science/computer-science"


def test_matches_page_section_and_contains():
    exp = {"page": "computer-science", "section": "major (0376):",
           "contains": "May be replaced by  STAT_V 200"}
    assert matches(URL, "B.Sc. > Computer Science > Major (0376): Computer Science (CPSC)",
                   "... [2] may be replaced by STAT_V 200 or ...", exp)


def test_matches_rejects_wrong_page_suffix():
    assert not matches(URL, "", "", {"page": "science"})


def test_matches_section_is_required_when_given():
    exp = {"page": "computer-science", "section": "Electives"}
    assert not matches(URL, "B.Sc. > Computer Science > Lecture-based courses", "", exp)


def hit(url, path="", content=""):
    return Hit(0, url, path, content, 0.0)


def test_first_rank_finds_any_accepted_answer():
    hits = [hit("https://x/registration"), hit(URL)]
    assert first_rank(hits, [{"page": "nope"}, {"page": "computer-science"}]) == 2
    assert first_rank(hits, [{"page": "nope"}]) is None


def test_summarize():
    s = summarize([1, 3, None, 7], k=5)
    assert s["recall@1"] == 0.25
    assert s["recall@5"] == 0.5
    assert abs(s["mrr@10"] - (1 + 1/3 + 1/7) / 4) < 1e-9
