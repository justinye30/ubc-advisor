"""Prerequisite graph queries.

prereq_edges is a flattened view of the requirement trees: one row per
(course, course its prerequisite mentions), with is_optional marking codes
that sit under a ONE_OF. Flattening loses *which* alternatives belong
together, so the graph is used for two things only:

  - finding candidates fast (what mentions CPSC 221?)
  - drawing the shape of what lies between a student and a course

Whether a student can actually take something is still decided by
evaluate() on the full tree. The graph narrows; the evaluator decides.
"""

import os
from collections import defaultdict
from dataclasses import dataclass, field

import psycopg
from psycopg.rows import DictRow, dict_row

from core.codes import KNOWN_RETIRED, is_in_scope, is_secondary_school
from core.evaluator import INDETERMINATE, NOT_SATISFIED, SATISFIED, Result, evaluate
from core.transcript import Transcript
from core.tree import course_codes


def connect() -> psycopg.Connection[DictRow]:
    return psycopg.Connection[DictRow].connect(os.environ["DATABASE_URL"], row_factory=dict_row)


# ------------------------------------------------------------------ reverse: what mentions X

@dataclass
class Dependent:
    code: str
    title: str | None
    is_optional: bool          # X is one alternative, not a hard requirement
    extraction_status: str
    prereq_tree: dict


def dependents(conn, code: str) -> list[Dependent]:
    """Courses whose prerequisites mention `code`. One indexed lookup."""
    rows = conn.cursor(row_factory=dict_row).execute(
        """
        SELECT c.code, c.title, e.is_optional, c.extraction_status, c.prereq_tree
        FROM prereq_edges e
        JOIN courses c ON c.code = e.course_code
        WHERE e.requires_code = %s AND e.relation = 'prereq'
        ORDER BY e.is_optional, c.code
        """,
        (code,),
    ).fetchall()
    return [Dependent(**r) for r in rows]


@dataclass
class Unlocks:
    """What taking one more course changes for a particular student."""
    newly_eligible: list[tuple[Dependent, Result]] = field(default_factory=list)
    to_confirm: list[tuple[Dependent, Result]] = field(default_factory=list)
    still_blocked: list[tuple[Dependent, Result]] = field(default_factory=list)
    already_eligible: list[Dependent] = field(default_factory=list)


def with_course(t: Transcript, code: str) -> Transcript:
    """The same transcript plus one completed course, grade unknown."""
    return Transcript(
        completed=t.completed | {code},
        grades=dict(t.grades),
        grade_ranges=dict(t.grade_ranges),
        credits=dict(t.credits),
        year=t.year,
        programs=set(t.programs),
    )


def unlocks_for(code: str, t: Transcript, candidates: list[Dependent]) -> Unlocks:
    """Re-evaluate each candidate with and without `code` on the transcript.

    The added course has no grade, so a candidate that needs e.g. 68% in it
    lands in to_confirm rather than newly_eligible. That's the honest answer:
    taking the course only unlocks it if the grade is high enough.
    """
    out = Unlocks()
    after_t = with_course(t, code)
    for dep in candidates:
        if dep.code in t.completed:
            continue
        before = evaluate(dep.prereq_tree, t)
        if before.state is SATISFIED:
            out.already_eligible.append(dep)
            continue
        after = evaluate(dep.prereq_tree, after_t)
        if after.state is SATISFIED:
            out.newly_eligible.append((dep, after))
        elif after.state is INDETERMINATE:
            out.to_confirm.append((dep, after))
        else:
            assert after.state is NOT_SATISFIED
            out.still_blocked.append((dep, after))
    return out


# ------------------------------------------------------------------ forward: what's beneath X

@dataclass
class EdgeRow:
    course: str
    requires: str
    optional: bool
    title: str | None          # of `requires`
    known: bool                # `requires` exists in courses
    status: str | None         # extraction_status of `requires`
    tree: dict | None = None   # prereq_tree of `requires`


ANCESTRY_SQL = """
WITH RECURSIVE walk(course_code, requires_code, is_optional) AS (
    SELECT e.course_code, e.requires_code, e.is_optional
    FROM prereq_edges e
    WHERE e.course_code = %(target)s AND e.relation = 'prereq'

  UNION   -- not UNION ALL: duplicates are dropped as we go, so the walk is
          -- bounded by distinct edges (not paths) and stops on cycles

    SELECT e.course_code, e.requires_code, e.is_optional
    FROM walk w
    JOIN prereq_edges e
      ON e.course_code = w.requires_code AND e.relation = 'prereq'
    WHERE NOT (w.requires_code = ANY(%(stop)s::text[]))   -- done: don't look beneath
)
SELECT w.course_code   AS course,
       w.requires_code AS requires,
       w.is_optional   AS optional,
       c.title,
       c.code IS NOT NULL AS known,
       c.extraction_status AS status,
       c.prereq_tree AS tree
FROM walk w
LEFT JOIN courses c ON c.code = w.requires_code
ORDER BY course, optional, requires
"""


def ancestry(conn, target: str, stop_at: frozenset[str] | set[str] = frozenset()) -> list[EdgeRow]:
    """Every prerequisite edge reachable from `target`, transitively.

    Doesn't expand beneath courses in `stop_at` (the student has them).
    """
    rows = conn.cursor(row_factory=dict_row).execute(
        ANCESTRY_SQL, {"target": target, "stop": sorted(stop_at)},
    ).fetchall()
    return [EdgeRow(**r) for r in rows]


def children_by_course(rows: list[EdgeRow]) -> dict[str, list[EdgeRow]]:
    out: dict[str, list[EdgeRow]] = defaultdict(list)
    for r in rows:
        out[r.course].append(r)
    return out


def always_required(target: str, rows: list[EdgeRow],
                    stop_at: frozenset[str] | set[str] = frozenset()) -> list[str]:
    """Courses reachable from `target` through required edges only.

    If A requires B and B requires C, with no alternatives at either step,
    then C is required for A. One optional hop anywhere breaks the chain:
    another route might avoid C entirely. Doesn't look beneath `stop_at`.
    """
    kids = children_by_course(rows)
    seen: list[str] = []
    stack = [target]
    while stack:
        code = stack.pop()
        if code in stop_at:
            continue
        for r in kids.get(code, []):
            if not r.optional and r.requires not in seen and r.requires != target:
                seen.append(r.requires)
                stack.append(r.requires)
    return seen


def is_okanagan(item: str) -> bool:
    return "_O " in item


class PathView:
    """The ancestry graph, pruned by what the evaluator says still matters.

    The SQL walk returns every course beneath the target, including whole
    families of alternatives the student has already satisfied another way.
    For each course we evaluate its own tree against the transcript and
    only follow the children that appear in the result's unmet/unknown
    lists. A course whose prerequisites are already met is "ready": it
    still has to be taken, but nothing beneath it needs attention.
    """

    def __init__(self, target: str, target_tree: dict | None,
                 rows: list[EdgeRow], t: Transcript):
        self.target = target
        self.t = t
        self.kids = children_by_course(rows)
        self.info = {r.requires: r for r in rows}
        self.trees = {r.requires: r.tree for r in rows}
        self.trees[target] = target_tree
        self._results: dict[str, Result | None] = {}
        self._blockers: dict[str, tuple[list[EdgeRow], list[tuple[str, str]]]] = {}
        self.hidden_okanagan = 0
        self.ready_shown: list[str] = []

    def result(self, code: str) -> Result | None:
        if code not in self._results:
            tree = self.trees.get(code)
            self._results[code] = evaluate(tree, self.t) if tree else None
        return self._results[code]

    def is_ready(self, code: str) -> bool:
        if code in self.t.completed:
            return False
        res = self.result(code)
        if res is not None:
            return res.state is SATISFIED
        row = self.info.get(code)
        return bool(row and row.known and row.status == "no_prereq")

    def ready(self) -> set[str]:
        return {c for c in self.trees if self.is_ready(c)}

    def settled_alternatives(self, code: str) -> set[str]:
        """Options not worth exploring: another member of the same ONE_OF
        can already be taken (or is done), so this branch is a detour."""
        tree = self.trees.get(code)
        out: set[str] = set()
        if not tree:
            return out

        def visit(n: dict) -> None:
            if n["op"] == "ONE_OF":
                members = course_codes(n)
                if any(m in self.t.completed or self.is_ready(m) for m in members):
                    out.update(m for m in members if m not in self.t.completed and not self.is_ready(m))
                    return
            for child in n.get("children", []):
                visit(child)
            if "child" in n:
                visit(n["child"])

        visit(tree)
        return out

    def blockers(self, code: str) -> tuple[list[EdgeRow], list[tuple[str, str]]]:
        """Children still in the way, plus non-course blockers as (mark, text)."""
        if code not in self._blockers:
            self._blockers[code] = self._compute_blockers(code)
        return self._blockers[code]

    def _compute_blockers(self, code: str) -> tuple[list[EdgeRow], list[tuple[str, str]]]:
        children = self.kids.get(code, [])
        res = self.result(code)
        if res is None:
            return children, []
        wanted = set(res.unmet) | set(res.unknown)
        child_codes = {r.requires for r in children}

        # Blockers that aren't child courses (standing, permission, credit
        # counts, unparsed clauses), described by the evaluator's own reasons.
        extras: list[tuple[str, str]] = []
        for reason in res.reasons:
            if reason.state is SATISFIED:
                continue
            subject = reason.text.split(":", 1)[0]
            if subject in child_codes:
                continue                      # drawn as a course line instead
            if is_okanagan(subject):
                self.hidden_okanagan += 1
                continue
            mark = "·" if reason.state is NOT_SATISFIED else "?"
            text = reason.text if len(reason.text) <= 60 else reason.text[:57] + "..."
            if (mark, text) not in extras:
                extras.append((mark, text))
        return [r for r in children if r.requires in wanted], extras

    def note_for(self, parent: str, r: EdgeRow) -> tuple[str, str]:
        code = r.requires
        parent_res = self.result(parent)
        if code in self.t.completed:
            if parent_res and code in parent_res.unmet:
                return "✓", "grade below requirement"
            if parent_res and code in parent_res.unknown:
                return "✓", "grade not reported"
            return "✓", ""
        if is_secondary_school(code):
            return "?", "high-school course"
        if code in KNOWN_RETIRED:
            return "?", "no longer offered"
        if not r.known:
            return "?", "not in current calendar" if is_in_scope(code) else "outside our data"
        if self.is_ready(code):
            return "→", "ready to take"
        note = "requirements flagged" if r.status == "flagged" else ""
        return "·", note

    def signature(self, code: str) -> tuple:
        children, extras = self.blockers(code)
        return (tuple(sorted((r.requires, r.optional) for r in children)), tuple(extras))

    def render(self) -> list[str]:
        drawn: set[str] = {self.target}
        first_with: dict[tuple, str] = {}     # identical blocker sets are drawn once
        lines: list[str] = []

        def visit(code: str, prefix: str) -> None:
            children, extras = self.blockers(code)
            detours = self.settled_alternatives(code)
            items: list[EdgeRow | str] = [*children, *(f"{m} {text}" for m, text in extras)]
            for i, r in enumerate(items):
                last = i == len(items) - 1
                branch = "└─ " if last else "├─ "
                if isinstance(r, str):
                    lines.append(f"{prefix}{branch}{r}")
                    continue
                mark, note = self.note_for(code, r)
                if mark == "→" and r.requires not in self.ready_shown:
                    self.ready_shown.append(r.requires)
                has_kids = bool(self.kids.get(r.requires))
                expand = mark == "·" and has_kids and r.requires not in drawn
                if expand and r.requires in detours:
                    expand, note = False, "(another option is ready)"
                elif expand:
                    sig = self.signature(r.requires)
                    if sig in first_with:
                        expand, note = False, f"(same as {first_with[sig]})"
                    else:
                        first_with[sig] = r.requires
                elif mark == "·" and has_kids and r.requires in drawn:
                    note = "(shown above)"
                tag = "option" if r.optional else "required"
                title = (r.title or "")[:30]
                lines.append(f"{prefix}{branch}{mark} {r.requires:<10} {tag:<9} {title:<30} {note}".rstrip())
                if expand:
                    drawn.add(r.requires)
                    visit(r.requires, prefix + ("   " if last else "│  "))

        visit(self.target, "")
        return lines