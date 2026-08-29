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
    """True if the normalized code's subject is one we ingest."""
    return code.split()[0] in IN_SCOPE_SUBJECTS


def subject_index_url(subject: str) -> str:
    """'CPSC' -> '.../course-descriptions/subject/cpscv'"""
    return f"{CALENDAR_BASE}/course-descriptions/subject/{subject.lower()}v"


def course_url(code: str) -> str:
    """'CPSC 221' -> '.../course-descriptions/courses/cpscv-221'

    Constructed, never fetched. Used for citations only.
    """
    subject, number = code.split()
    return f"{CALENDAR_BASE}/course-descriptions/courses/{subject.lower()}v-{number.lower()}"
