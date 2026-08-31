"""Deterministic tri-state evaluation of requirement trees.

No LLM involvement. Given a tree and a transcript, this decides eligibility
and explains itself. The explanation is generated from the evaluation trace,
so grounding is structural rather than hoped-for.
"""

from dataclasses import dataclass, field
from enum import Enum

from core.transcript import Transcript


class State(Enum):
    SATISFIED = "SATISFIED"
    NOT_SATISFIED = "NOT_SATISFIED"
    INDETERMINATE = "INDETERMINATE"


SATISFIED = State.SATISFIED
NOT_SATISFIED = State.NOT_SATISFIED
INDETERMINATE = State.INDETERMINATE


@dataclass
class Reason:
    """A single explanation, tagged with the state it justifies."""
    state: State
    text: str


@dataclass
class Result:
    state: State
    reasons: list[Reason] = field(default_factory=list)
    unmet: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    @property
    def eligible(self) -> bool:
        return self.state is SATISFIED

    @property
    def blocking(self) -> list[str]:
        """Every reason whose state matches the verdict."""
        return [r.text for r in self.reasons if r.state is self.state]

    @property
    def headline(self) -> str:
        blocking = self.blocking
        if blocking:
            return blocking[0]
        return self.reasons[0].text if self.reasons else ""


def evaluate(node: dict, t: Transcript) -> Result:
    op = node["op"]

    # ---- combinators ----

    if op == "ALL_OF":
        results = [evaluate(c, t) for c in node["children"]]
        reasons = [r for res in results for r in res.reasons]
        unmet = [u for res in results for u in res.unmet]
        unknown = [u for res in results for u in res.unknown]

        # A provably unmet requirement beats uncertainty elsewhere.
        if any(r.state is NOT_SATISFIED for r in results):
            return Result(NOT_SATISFIED, reasons, unmet, unknown)
        if any(r.state is INDETERMINATE for r in results):
            return Result(INDETERMINATE, reasons, unmet, unknown)
        return Result(SATISFIED, reasons, unmet, unknown)

    if op == "ONE_OF":
        results = [evaluate(c, t) for c in node["children"]]

        # A satisfied branch short-circuits: other branches are irrelevant.
        for res in results:
            if res.state is SATISFIED:
                return Result(SATISFIED, res.reasons)

        reasons = [r for res in results for r in res.reasons]
        unmet = [u for res in results for u in res.unmet]
        unknown = [u for res in results for u in res.unknown]

        if any(r.state is INDETERMINATE for r in results):
            return Result(INDETERMINATE, reasons, unmet, unknown)
        return Result(NOT_SATISFIED, reasons, unmet, unknown)

    # ---- leaves ----

    if op == "COURSE":
        code = node["code"]
        if t.has(code):
            return Result(SATISFIED, [Reason(SATISFIED, f"{code}: completed")])
        if node.get("tracked", True):
            return Result(NOT_SATISFIED,
                          [Reason(NOT_SATISFIED, f"{code}: not completed")],
                          unmet=[code])
        # We do not hold this course, so absence is not evidence of absence.
        return Result(
            INDETERMINATE,
            [Reason(INDETERMINATE, f"{code}: outside our course data — confirm yourself")],
            unknown=[code],
        )

    if op == "MIN_GRADE":
        percent = node["percent"]
        inner = evaluate(node["child"], t)
        if inner.state is not SATISFIED:
            return inner

        # Which course actually satisfied the child?
        satisfying = [c for c in _codes(node["child"]) if t.has(c)]
        graded: list[tuple[str, int]] = []
        for c in satisfying:
            g = t.grade(c)
            if g is not None:
                graded.append((c, g))

        if not graded:
            codes = ", ".join(satisfying) or "the required course"
            return Result(
                INDETERMINATE,
                [Reason(INDETERMINATE, f"{codes}: needs {percent}%, grade not reported")],
                unknown=satisfying,
            )
        if any(g >= percent for _, g in graded):
            best = max(graded, key=lambda x: x[1])
            return Result(SATISFIED, [Reason(SATISFIED, f"{best[0]}: {best[1]}% ≥ {percent}%")])
        best_attempt = max(graded, key=lambda x: x[1])
        return Result(
            NOT_SATISFIED,
            [Reason(NOT_SATISFIED, f"{best_attempt[0]}: {best_attempt[1]}% < {percent}% required")],
            unmet=[best_attempt[0]],
        )

    if op == "MIN_CREDITS":
        spec = node.get("from", {})
        needed = node["credits"]
        earned = 0.0
        matched = []
        for code in t.completed:
            if _matches(code, spec):
                earned += t.credits.get(code, 3.0)
                matched.append(code)
        if earned >= needed:
            return Result(SATISFIED, [Reason(SATISFIED, f"{earned:g} credits from {', '.join(matched)}")])
        return Result(
            INDETERMINATE,
            [Reason(INDETERMINATE, f"needs {needed:g} credits from {_describe(spec)}; "
             f"found {earned:g} in reported courses")],
            unknown=[_describe(spec)],
        )

    if op == "STANDING":
        if t.year is None:
            return Result(INDETERMINATE, [Reason(INDETERMINATE, "year standing not provided")],
                          unknown=["year standing"])
        if t.year >= node["year"]:
            return Result(SATISFIED, [Reason(SATISFIED, f"year {t.year} ≥ {node['year']}")])
        return Result(NOT_SATISFIED,
                      [Reason(NOT_SATISFIED, f"year {t.year}, needs {node['year']}")],
                      unmet=[f"year {node['year']} standing"])

    if op == "PROGRAM":
        name = node["name"]
        if not t.programs:
            return Result(INDETERMINATE, [Reason(INDETERMINATE, f"program not provided (needs {name})")],
                          unknown=[name])
        if name.lower() in {p.lower() for p in t.programs}:
            return Result(SATISFIED, [Reason(SATISFIED, f"registered in {name}")])
        return Result(NOT_SATISFIED, [Reason(NOT_SATISFIED, f"not registered in {name}")], unmet=[name])

    if op == "OUT_OF_SCOPE":
        code = node["code"]
        if t.has(code):
            return Result(SATISFIED, [Reason(SATISFIED, f"{code}: completed")])
        return Result(INDETERMINATE,
                      [Reason(INDETERMINATE, f"{code}: Okanagan course, outside our data")],
                      unknown=[code])

    if op == "PERMISSION":
        note = node.get("note", "permission required")
        return Result(INDETERMINATE, [Reason(INDETERMINATE, note)], unknown=[note])

    if op == "EXTERNAL_LIST":
        desc = node.get("description", "an external list")
        return Result(INDETERMINATE,
                      [Reason(INDETERMINATE, f"depends on {desc} — not in our data")],
                      unknown=[desc])

    if op == "UNPARSED":
        text = node["text"]
        return Result(INDETERMINATE,
                      [Reason(INDETERMINATE, f'could not interpret: "{text}"')],
                      unknown=[text])

    raise ValueError(f"unknown op: {op!r}")


def _codes(node: dict) -> list[str]:
    """Course codes directly reachable from a node (for MIN_GRADE)."""
    if node["op"] in {"COURSE", "OUT_OF_SCOPE"}:
        return [node["code"]]
    out = []
    for child in node.get("children", []):
        out.extend(_codes(child))
    if "child" in node:
        out.extend(_codes(node["child"]))
    return out


def _matches(code: str, spec: dict) -> bool:
    if code in spec.get("courses", []):
        return True
    parts = code.split()
    if len(parts) != 2:
        return False
    subject, number = parts
    if subject not in spec.get("subjects", []):
        return False
    level_min = spec.get("level_min")
    if level_min is None:
        return True
    return int(number.rstrip("ABCDEFGH")) >= level_min


def _describe(spec: dict) -> str:
    parts = []
    if spec.get("subjects"):
        parts.append("/".join(spec["subjects"]))
    if spec.get("level_min"):
        parts.append(f"at {spec['level_min']} level or above")
    if spec.get("courses"):
        parts.append(f"one of {', '.join(spec['courses'])}")
    return " ".join(parts) or "a specified set"
