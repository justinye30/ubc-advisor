"""Recompute the `tracked` flag on stored trees. No API calls.

`tracked` is derivable from the course code via is_in_scope(), so it was a
mistake to have the model decide it. This applies the deterministic version
to trees already extracted.

Run:  python -m scripts.backfill_tracked
"""

import json
import os

import psycopg
from dotenv import load_dotenv

from core.codes import is_in_scope
from core.tree import walk

load_dotenv()


def fix_tracked(node: dict) -> int:
    """Overwrite tracked on every COURSE node. Returns how many changed."""
    changed = 0
    for n in walk(node):
        if n["op"] == "COURSE":
            correct = is_in_scope(n["code"])
            if n.get("tracked") != correct:
                n["tracked"] = correct
                changed += 1
    return changed


def main() -> int:
    total_nodes = total_courses = 0
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code, prereq_tree FROM courses WHERE prereq_tree IS NOT NULL"
            )
            rows = cur.fetchall()

        for code, tree in rows:
            n = fix_tracked(tree)
            if n:
                total_courses += 1
                total_nodes += n
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE courses SET prereq_tree = %s WHERE code = %s",
                        (json.dumps(tree), code),
                    )
        conn.commit()

    print(f"corrected {total_nodes} nodes across {total_courses} courses "
          f"(of {len(rows)} with trees)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
