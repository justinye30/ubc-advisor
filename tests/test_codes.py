import pytest

from core.codes import (
    OutOfScope,
    course_url,
    is_in_scope,
    normalize,
    subject_index_url,
    try_normalize,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("CPSC 221", "CPSC 221"),
        ("CPSC_V 221", "CPSC 221"),
        ("cpsc 221", "CPSC 221"),
        ("CPSC221", "CPSC 221"),
        ("  CPSC  221  ", "CPSC 221"),
        ("CPSC 221.", "CPSC 221"),
        ("CPSC 221,", "CPSC 221"),
        ("MATH 100A", "MATH 100A"),
        ("MATH_V 100a", "MATH 100A"),
        ("WRDS 150", "WRDS 150"),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_okanagan_is_out_of_scope():
    with pytest.raises(OutOfScope):
        normalize("MATH_O 220")


@pytest.mark.parametrize("raw", ["", "hello", "CPSC", "221", "CPSC 22", "TOOLONGSUBJ 221"])
def test_rejects_non_codes(raw):
    with pytest.raises(ValueError):
        normalize(raw)


def test_try_normalize_returns_none():
    assert try_normalize("not a course") is None
    assert try_normalize("MATH_O 220") is None
    assert try_normalize("CPSC_V 221") == "CPSC 221"


def test_vancouver_and_okanagan_do_not_collide():
    """The bug this whole module exists to prevent."""
    assert normalize("MATH_V 220") == "MATH 220"
    with pytest.raises(OutOfScope):
        normalize("MATH_O 220")


def test_scope_check():
    assert is_in_scope("CPSC 221")
    assert not is_in_scope("BIOL 121")


def test_urls():
    assert subject_index_url("CPSC").endswith("/subject/cpscv")
    assert course_url("CPSC 221").endswith("/courses/cpscv-221")
    assert course_url("MATH 100A").endswith("/courses/mathv-100a")

def test_high_school_codes_are_out_of_scope():
    assert not is_in_scope("PHYS 12")
    assert not is_in_scope("MATH 12")
    assert is_in_scope("PHYS 101")