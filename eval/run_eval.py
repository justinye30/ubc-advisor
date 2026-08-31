"""Measure extraction accuracy against the hand-labeled golden set.

Compares stored prereq_tree against eval/golden_courses.yaml using
order-insensitive structural equality.

Run:  python -m eval.run_eval [--verbose]
"""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import psycopg
import yaml
from dotenv import load_dotenv

from core.tree import TreeError, canonical, node_type_counts, validate

load_dotenv()
GOLDEN = Path(__file__).parent / "golden_courses.yaml"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true", help="show every mismatch")
    args = ap.parse_args()

    golden = yaml.safe_load(GOLDEN.read_text())
    print(f"golden set: {len(golden)} courses\n")

    bad = []
    for entry in golden:
        if entry.get("tree") is None:
            continue
        try:
            validate(entry["tree"])
        except (TreeError, TypeError, KeyError) as exc:
            bad.append((entry["code"], exc))

    if bad:
        print("malformed labels — fix these before evaluating:")
        for code, exc in bad:
            print(f"  {code:<12} {exc}")
        return 1

    exact = wrong = missing = 0
    failures_by_type: Counter = Counter()
    mismatches = []

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        for entry in golden:
            code = entry["code"]
            expected = entry["tree"]

            cur.execute(
                "SELECT prereq_tree, extraction_status FROM courses WHERE code = %s",
                (code,),
            )
            row = cur.fetchone()
            if row is None:
                print(f"  {code:<12} NOT IN DB")
                missing += 1
                continue

            actual, status = row

            if expected is None and actual is None:
                exact += 1
                continue
            if expected is None or actual is None:
                wrong += 1
                mismatches.append((code, status, expected, actual))
                continue

            if canonical(expected) == canonical(actual):
                exact += 1
            else:
                wrong += 1
                mismatches.append((code, status, expected, actual))
                # Attribute the failure to node types present in the label
                for op in node_type_counts(expected):
                    failures_by_type[op] += 1

    total = exact + wrong + missing
    print(f"\n{'='*60}")
    print(f"exact match     {exact:>3} / {total}   ({exact/total:.1%})")
    print(f"mismatched      {wrong:>3}")
    print(f"missing from db {missing:>3}")

    if failures_by_type:
        print(f"\nfailures by node type present in label:")
        for op, n in failures_by_type.most_common():
            print(f"  {op:<16} {n}")

    if args.verbose and mismatches:
        for code, status, expected, actual in mismatches:
            print(f"\n{'-'*60}\n{code}  (status={status})")
            print("EXPECTED:", json.dumps(expected, indent=2))
            print("ACTUAL:  ", json.dumps(actual, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
