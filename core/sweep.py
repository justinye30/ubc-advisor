"""What can a student take? Bucket every course in scope by verdict.

The CLI's `sweep` command does the same thing inline; this is the shared,
presentation-free version the agent uses.
"""

from dataclasses import dataclass, field

from core.evaluator import INDETERMINATE, SATISFIED, Result, evaluate
from core.repo import Course, list_courses
from core.transcript import Transcript

GRADUATE_LEVEL = 500


@dataclass
class Sweep:
    eligible: list[Course] = field(default_factory=list)
    no_prereq: list[Course] = field(default_factory=list)
    to_confirm: list[tuple[Course, Result]] = field(default_factory=list)
    not_yet: list[tuple[Course, Result]] = field(default_factory=list)
    unparsed: list[Course] = field(default_factory=list)


def level(code: str) -> int:
    digits = "".join(ch for ch in code.split()[-1] if ch.isdigit())
    return int(digits) if digits else 0


def bucket(courses: list[Course], t: Transcript, include_graduate: bool = False) -> Sweep:
    out = Sweep()
    for c in courses:
        if c.code in t.completed:
            continue
        if not include_graduate and level(c.code) >= GRADUATE_LEVEL:
            continue
        if c.prereq_tree is None:
            (out.no_prereq if c.extraction_status == "no_prereq" else out.unparsed).append(c)
            continue
        result = evaluate(c.prereq_tree, t)
        if result.state is SATISFIED:
            out.eligible.append(c)
        elif result.state is INDETERMINATE:
            out.to_confirm.append((c, result))
        else:
            out.not_yet.append((c, result))
    return out


def sweep(t: Transcript, subjects: set[str], include_graduate: bool = False) -> Sweep:
    courses = [c for s in sorted(subjects) for c in list_courses(subject=s)]
    return bucket(courses, t, include_graduate)
