"""A student's academic record, as much as we know of it."""

from dataclasses import dataclass, field

# UBC Vancouver letter grades and the percentage band each covers.
LETTER_GRADES: dict[str, tuple[int, int]] = {
    "A+": (90, 100), "A": (85, 89), "A-": (80, 84),
    "B+": (76, 79), "B": (72, 75), "B-": (68, 71),
    "C+": (64, 67), "C": (60, 63), "C-": (55, 59),
    "D": (50, 54), "F": (0, 49),
}


@dataclass
class Transcript:
    """What we know about a student.

    grades maps course code -> percent. grade_ranges maps course code ->
    (low, high) when only a letter grade is known. A course present in
    `completed` with neither means "passed, grade unknown" — which forces
    INDETERMINATE on any MIN_GRADE node touching it, rather than assuming.
    """

    completed: set[str] = field(default_factory=set)
    grades: dict[str, int] = field(default_factory=dict)
    grade_ranges: dict[str, tuple[int, int]] = field(default_factory=dict)
    credits: dict[str, float] = field(default_factory=dict)
    year: int | None = None
    programs: set[str] = field(default_factory=set)

    @classmethod
    def parse(cls, spec: str, year: int | None = None,
              programs: set[str] | None = None) -> "Transcript":
        """Build from 'CPSC 110, CPSC 121:87, MATH 200:B+'.

        A bare code means passed with unknown grade.
        """
        completed: set[str] = set()
        grades: dict[str, int] = {}
        ranges: dict[str, tuple[int, int]] = {}
        for item in (s.strip() for s in spec.split(",") if s.strip()):
            if ":" in item:
                code, mark = (p.strip() for p in item.rsplit(":", 1))
                if mark.isdigit():
                    grades[code] = int(mark)
                elif mark.upper() in LETTER_GRADES:
                    ranges[code] = LETTER_GRADES[mark.upper()]
                else:
                    raise ValueError(f"unrecognized grade {mark!r} for {code}")
            else:
                code = item
            completed.add(code)
        return cls(
            completed=completed,
            grades=grades,
            grade_ranges=ranges,
            year=year,
            programs=programs or set(),
        )

    def has(self, code: str) -> bool:
        return code in self.completed

    def grade(self, code: str) -> int | None:
        return self.grades.get(code)

    def grade_range(self, code: str) -> tuple[int, int] | None:
        """(low, high) percent bounds, from an exact grade or a letter."""
        if code in self.grades:
            g = self.grades[code]
            return (g, g)
        return self.grade_ranges.get(code)
