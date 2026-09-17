"""Measure entity extraction against eval/entities_questions.yaml.

Checks labels against the course catalogue first. Then extracts each
question once and compares, field by field, what survived validation with
what should have. Also counts what validation threw away — each of those is
a model mistake that didn't reach a verdict.

Run:  python -m eval.run_entities_eval [--save PATH] [--questions FILE]
"""

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from agent.entities import ENTITY_MODEL, Entities, EntityError, catalogue, extract
from core.codes import IN_SCOPE_SUBJECTS
from core.transcript import LETTER_GRADES

load_dotenv()
QUESTIONS = Path(__file__).parent / "entities_questions.yaml"
FIELDS = ["targets", "completed", "in_progress", "year", "ambiguous", "transcript_given"]
LETTER_FOR_RANGE = {tuple(v): k for k, v in LETTER_GRADES.items()}


# ------------------------------------------------------------------ comparison (pure)

def expected_of(q: dict) -> dict:
    return {
        "targets": sorted(q.get("targets") or []),
        "completed": {k: v for k, v in (q.get("completed") or {}).items()},
        "in_progress": sorted(q.get("in_progress") or []),
        "year": q.get("year"),
        "ambiguous": sorted(a.lower() for a in q.get("ambiguous") or []),
        "transcript_given": not q.get("no_transcript", False),
    }


def actual_of(e: Entities) -> dict:
    completed: dict[str, int | str | None] = {c: None for c in e["completed"]}
    completed.update(e["grades"])
    completed.update({c: LETTER_FOR_RANGE.get(tuple(r), f"{r[0]}-{r[1]}")
                      for c, r in e["grade_ranges"].items()})
    return {
        "targets": sorted(e["targets"]),
        "completed": completed,
        "in_progress": sorted(e["in_progress"]),
        "year": e["year"],
        "ambiguous": sorted(a["as_written"].lower() for a in e["ambiguous"]),
        "transcript_given": e["transcript_given"],
    }


def extra_codes(expected: dict, actual: dict) -> set[str]:
    want = set(expected["targets"]) | set(expected["completed"]) | set(expected["in_progress"])
    got = set(actual["targets"]) | set(actual["completed"]) | set(actual["in_progress"])
    return got - want


def check_labels(questions: list[dict], cat: set[str]) -> list[str]:
    bad = []
    for q in questions:
        exp = expected_of(q)
        for code in [*exp["targets"], *exp["completed"], *exp["in_progress"]]:
            if code not in cat:
                bad.append(f"{q['id']}: {code} is not in courses")
        for frag in exp["ambiguous"]:
            n = sum(1 for c in cat if c.split()[-1] == frag and c.split()[0] in IN_SCOPE_SUBJECTS)
            if n < 2:
                bad.append(f"{q['id']}: '{frag}' matches {n} course(s), so it isn't ambiguous")
    return bad


# ------------------------------------------------------------------ main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", type=Path)
    ap.add_argument("--questions", type=Path, default=QUESTIONS, help="question file")
    args = ap.parse_args()

    questions = yaml.safe_load(args.questions.read_text())
    cat = set(catalogue())
    bad = check_labels(questions, cat)
    if bad:
        print("LABEL ERRORS — fix these before trusting any number:\n")
        print("\n".join(f"  {b}" for b in bad))
        return 2

    print(f"{args.questions.name}: {len(questions)} questions · {ENTITY_MODEL}")
    field_ok: Counter = Counter()
    exact, extras, rejected, errors = 0, 0, 0, 0
    records, failures = [], []

    for q in questions:
        exp = expected_of(q)
        try:
            e = extract(q["question"])
        except EntityError as exc:
            errors += 1
            failures.append((q, exp, None, None, str(exc)))
            print("E", end="", flush=True)
            continue
        act = actual_of(e)
        wrong = [f for f in FIELDS if exp[f] != act[f]]
        for f in FIELDS:
            field_ok[f] += f not in wrong
        exact += not wrong
        extras += len(extra_codes(exp, act))
        rejected += len(e["rejected"])
        records.append({"id": q["id"], "wrong": wrong, "actual": act, "entities": e})
        if wrong:
            failures.append((q, exp, act, e, None))
        print("." if not wrong else "x", end="", flush=True)
    print()

    n = len(questions)
    print(f"\nexact match           {exact}/{n}  ({exact / n:.0%})")
    for f in FIELDS:
        print(f"  {f:<20} {field_ok[f]}/{n - errors}")
    print(f"extra codes reaching a verdict   {extras}")
    print(f"model outputs rejected by validation   {rejected}")
    if errors:
        print(f"ERRORS {errors}")

    for q, exp, act, e, err in failures:
        print(f"\n  {q['id']}: {q['question']}")
        if err:
            print(f"    error: {err}")
            continue
        assert act is not None and e is not None
        for f in FIELDS:
            if exp[f] != act[f]:
                print(f"    {f:<17} expected {exp[f]}   got {act[f]}")
        for note in e["rejected"]:
            print(f"    rejected: {note}")
        for note in e["assumptions"]:
            print(f"    assumed:  {note}")

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps({
            "questions": args.questions.name,
            "model": ENTITY_MODEL,
            "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "exact": exact, "n": n, "fields": dict(field_ok),
            "extra_codes": extras, "rejected": rejected, "records": records,
        }, indent=2, default=str))
        print(f"\nsaved {args.save}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
