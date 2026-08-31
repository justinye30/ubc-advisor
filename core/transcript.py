"""A student's academic record, as much as we know of it."""

from dataclasses import dataclass, field


@dataclass
class Transcript:
    """What we know about a student.

    grades maps course code -> percent. A course present in `completed` but
    absent from `grades` means "passed, grade unknown" — which forces
    INDETERMINATE on any MIN_GRADE node touching it, rather than assuming.
    """

    completed: set[str] = field(default_factory=set)
    grades: dict[str, int] = field(default_factory=dict)
    credits: dict[str, float] = field(default_factory=dict)
    year: int | None = None
    programs: set[str] = field(default_factory=set)

    @classmethod
    def parse(cls, spec: str, year: int | None = None,
              programs: set[str] | None = None) -> "Transcript":
        """Build from 'CPSC 110, CPSC 121:87, MATH 200:74'.

        A bare code means passed with unknown grade.
        """
        completed: set[str] = set()
        grades: dict[str, int] = {}
        for item in (s.strip() for s in spec.split(",") if s.strip()):
            if ":" in item:
                code, pct = item.rsplit(":", 1)
                code = code.strip()
                grades[code] = int(pct)
            else:
                code = item
            completed.add(code)
        return cls(
            completed=completed,
            grades=grades,
            year=year,
            programs=programs or set(),
        )

    def has(self, code: str) -> bool:
        return code in self.completed

    def grade(self, code: str) -> int | None:
        return self.grades.get(code)
