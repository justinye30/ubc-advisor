from core.repo import Course
from core.sweep import bucket, level
from core.transcript import Transcript


def course(code, tree=None, status="parsed"):
    return Course(code=code, title=code, credits=3, prereq_text=None,
                  prereq_tree=tree, extraction_status=status, source_url="u")


def C(code):
    return {"op": "COURSE", "code": code, "tracked": True}


def test_level():
    assert level("CPSC 110") == 110
    assert level("MATH 100A") == 100


def test_bucket_sorts_by_verdict_and_skips_what_does_not_apply():
    courses = [
        course("CPSC 110", status="no_prereq"),                       # completed: skipped
        course("CPSC 100", status="no_prereq"),
        course("CPSC 210", {"op": "ALL_OF", "children": [C("CPSC 110")]}),
        course("CPSC 213", {"op": "ALL_OF", "children": [C("CPSC 121")]}),
        course("CPSC 340", {"op": "STANDING", "year": 3}),
        course("CPSC 500", {"op": "ALL_OF", "children": [C("CPSC 110")]}),  # graduate
        course("CPSC 399", status="flagged"),
    ]
    s = bucket(courses, Transcript.parse("CPSC 110"))
    assert [c.code for c in s.eligible] == ["CPSC 210"]
    assert [c.code for c in s.no_prereq] == ["CPSC 100"]
    assert [c.code for c, _ in s.to_confirm] == ["CPSC 340"]
    assert [c.code for c, _ in s.not_yet] == ["CPSC 213"]
    assert [c.code for c in s.unparsed] == ["CPSC 399"]


def test_bucket_can_include_graduate_courses():
    courses = [course("CPSC 500", {"op": "ALL_OF", "children": [C("CPSC 110")]})]
    assert bucket(courses, Transcript.parse("CPSC 110"), include_graduate=True).eligible
