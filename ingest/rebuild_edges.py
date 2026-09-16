"""Rebuild prereq_edges from courses.prereq_tree.

Edges are derived data: everything in them is already in the trees. So
they can be regenerated at any time, deterministically, with no LLM call,
whenever the flattening logic in core.tree.edges() changes.

Run:  python -m ingest.rebuild_edges [--dry-run]
"""

import argparse
import logging
import os
import sys

import psycopg
from dotenv import load_dotenv

from core.tree import edges
from core.codes import KNOWN_RETIRED, is_in_scope, is_secondary_school

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("edges")

Edge = tuple[str, str, bool]   # (course_code, requires_code, is_optional)


def derive(rows: list[tuple[str, dict]]) -> tuple[set[Edge], list[str]]:
    """All edges implied by the trees, plus any self-references (skipped)."""
    out: set[Edge] = set()
    self_refs: list[str] = []
    for code, tree in rows:
        for requires, optional in edges(tree):
            if requires == code:
                self_refs.append(code)
                continue
            out.add((code, requires, optional))
    return out, self_refs


def classify_dead_ends(codes: set[str]) -> dict[str, list[str]]:
    """Split codes missing from `courses` by what their absence means."""
    groups: dict[str, list[str]] = {
        "high_school": [], "retired": [], "unexplained": [], "out_of_scope": [],
    }
    for code in sorted(codes):
        if is_secondary_school(code):
            groups["high_school"].append(code)
        elif code in KNOWN_RETIRED:
            groups["retired"].append(code)
        elif is_in_scope(code):
            groups["unexplained"].append(code)   # retired, or a parser gap
        else:
            groups["out_of_scope"].append(code)
    return groups


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report changes, write nothing")
    args = ap.parse_args()

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        trees = conn.execute(
            "SELECT code, prereq_tree FROM courses WHERE prereq_tree IS NOT NULL"
        ).fetchall()
        old: set[Edge] = {
            (a, b, o) for a, b, o in conn.execute(
                "SELECT course_code, requires_code, is_optional "
                "FROM prereq_edges WHERE relation = 'prereq'"
            ).fetchall()
        }
        known = {r[0] for r in conn.execute("SELECT code FROM courses").fetchall()}

        new, self_refs = derive(trees)

        added, removed = new - old, old - new
        log.info("%d trees → %d edges (%d required, %d optional)",
                 len(trees), len(new),
                 sum(not o for *_, o in new), sum(o for *_, o in new))
        log.info("changes vs current table: +%d  -%d", len(added), len(removed))
        for a, b, o in sorted(added)[:15]:
            log.info("  + %-10s requires %-10s %s", a, b, "optional" if o else "REQUIRED")
        for a, b, o in sorted(removed)[:15]:
            log.info("  - %-10s requires %-10s %s", a, b, "optional" if o else "REQUIRED")

        dead = classify_dead_ends({b for _, b, _ in new if b not in known})
        log.info("dead ends: %d out-of-scope subjects, %d high-school, %d known retired",
                 len(dead["out_of_scope"]), len(dead["high_school"]), len(dead["retired"]))
        if dead["unexplained"]:
            log.warning("%d unexplained in-scope codes (retired, or missed by the parser?): %s",
                        len(dead["unexplained"]), ", ".join(dead["unexplained"]))

        if args.dry_run:
            log.info("dry run — nothing written")
            return 0

        with conn.cursor() as cur:
            cur.execute("DELETE FROM prereq_edges WHERE relation = 'prereq'")
            cur.executemany(
                "INSERT INTO prereq_edges (course_code, requires_code, relation, is_optional) "
                "VALUES (%s, %s, 'prereq', %s)",
                sorted(new),
            )
        conn.commit()

        cycles = conn.execute(
            """
            SELECT a.course_code, a.requires_code
            FROM prereq_edges a
            JOIN prereq_edges b
              ON b.course_code = a.requires_code AND b.requires_code = a.course_code
            WHERE a.course_code < a.requires_code
            """
        ).fetchall()
        if cycles:
            log.warning("mutual requirements (2-cycles): %s",
                        ", ".join(f"{a}↔{b}" for a, b in cycles))

    log.info("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
