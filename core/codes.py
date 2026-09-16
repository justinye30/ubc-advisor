"""Course code normalization and URL construction.

Canonical form is 'CPSC 221' — subject, single space, number.
Every insertion path must call normalize() so the database never
sees divergent forms of the same course.
"""

import re

CALENDAR_BASE = "https://vancouver.calendar.ubc.ca"

# 'CPSC_V 221', 'cpsc221', 'MATH 100A' — subject, optional campus tag, number
_CODE_RE = re.compile(
    r"^([A-Za-z]{2,5})(?:_([VO]))?\s*(\d{3})([A-Za-z]?)$"
)

# Subjects in scope for this project (Vancouver, CS student's universe)
IN_SCOPE_SUBJECTS = frozenset(
    {"CPSC", "MATH", "STAT", "DSCI", "CPEN", "PHYS", "ENGL", "WRDS", "SCIE"}
)

KNOWN_RETIRED = frozenset(
    {"CPEN 322", "CPSC 261", "ENGL 112", "PHYS 257", "PHYS 313", "SCIE 120", "STAT 241"}
)

_CODE_IN_TEXT = re.compile(r"\b([A-Za-z]{2,5})(?:_([VvOo]))?\s*(\d{3}[A-Za-z]?)\b")

class OutOfScope(Exception):
    """Raised for codes that are valid but outside this project's scope."""


def normalize(raw: str) -> str:
    """'CPSC_V 221' -> 'CPSC 221'.

    Raises ValueError if the string is not a course code at all.
    Raises OutOfScope for Okanagan (_O) codes.
    """
    cleaned = raw.strip().strip(".,;:()")
    match = _CODE_RE.match(cleaned)
    if not match:
        raise ValueError(f"not a course code: {raw!r}")

    subject, campus, number, suffix = match.groups()

    if campus == "O":
        raise OutOfScope(f"Okanagan course: {raw!r}")

    return f"{subject.upper()} {number}{suffix.upper()}"


def try_normalize(raw: str) -> str | None:
    """normalize() but returns None instead of raising. For bulk parsing."""
    try:
        return normalize(raw)
    except (ValueError, OutOfScope):
        return None


def is_in_scope(code: str) -> bool:
    """True if the code is a UBC course in an ingested subject.

    Excludes BC secondary school courses (PHYS 12, MATH 12, PREC 12), which
    share subject prefixes with UBC courses but use two-digit numbers.
    """
    parts = code.split()
    if len(parts) != 2:
        return False
    subject, number = parts
    return subject in IN_SCOPE_SUBJECTS and len(number.rstrip("ABCDEFGH")) == 3


def is_secondary_school(code: str) -> bool:
    """True for BC high-school courses written like codes: 'PHYS 12', 'PREC 11'."""
    parts = code.split()
    return len(parts) == 2 and parts[0].isalpha() and parts[1] in {"10", "11", "12"}


def find_codes(text: str) -> list[str]:
    """Explicit course codes in a question, normalized, in order of appearance.

    Deliberately conservative: a subject must be one we ingest or be written
    in capitals, so "take 300-level courses" doesn't yield "TAKE 300". Bare
    numbers ("can I take 320?") are left for LLM entity extraction.
    Okanagan (_O) codes are skipped.
    """
    found: list[str] = []
    for subject, campus, number in _CODE_IN_TEXT.findall(text):
        if campus.upper() == "O":
            continue
        if subject.upper() not in IN_SCOPE_SUBJECTS and not subject.isupper():
            continue
        code = f"{subject.upper()} {number.upper()}"
        if code not in found:
            found.append(code)
    return found


def subject_index_url(subject: str) -> str:
    """'CPSC' -> '.../course-descriptions/subject/cpscv'"""
    return f"{CALENDAR_BASE}/course-descriptions/subject/{subject.lower()}v"


def course_url(code: str) -> str:
    """'CPSC 221' -> '.../course-descriptions/courses/cpscv-221'

    Constructed, never fetched. Used for citations only.
    """
    subject, number = code.split()
    return f"{CALENDAR_BASE}/course-descriptions/courses/{subject.lower()}v-{number.lower()}"
