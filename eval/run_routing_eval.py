"""Measure the router against eval/routing_questions.yaml.

Reports overall accuracy, a confusion matrix, per-intent recall, how often
non-eligibility questions were pulled into eligibility (the predicted
failure mode), and out-of-scope refusal correctness. With --runs N, also
reports questions whose route changed between runs.

Run:  python -m eval.run_routing_eval [--runs 2] [--save PATH]
"""

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from agent.router import INTENTS, PROMPT_VERSION, ROUTER_MODEL, RouteError, classify

load_dotenv()
QUESTIONS = Path(__file__).parent / "routing_questions.yaml"
ERROR = "error"


# ------------------------------------------------------------------ scoring (pure)

def confusion(pairs: list[tuple[str, str]]) -> dict[str, Counter]:
    """expected -> Counter(predicted)"""
    out: dict[str, Counter] = {}
    for expected, predicted in pairs:
        out.setdefault(expected, Counter())[predicted] += 1
    return out


def score(questions: list[dict], preds: dict[str, dict]) -> dict:
    pairs = [(q["intent"], preds[q["id"]]["intent"]) for q in questions]
    n = len(pairs) or 1
    matrix = confusion(pairs)

    recall = {}
    for intent in INTENTS:
        row = matrix.get(intent, Counter())
        total = sum(row.values())
        recall[intent] = row[intent] / total if total else None

    oos = [q for q in questions if q["intent"] == "out_of_scope"]
    in_scope = [q for q in questions if q["intent"] != "out_of_scope"]
    scope_ok = [q for q in oos if preds[q["id"]]["intent"] == "out_of_scope"
                and preds[q["id"]].get("scope_reason") == q.get("scope")]

    return {
        "accuracy": sum(e == p for e, p in pairs) / n,
        "recall": recall,
        "matrix": {k: dict(v) for k, v in matrix.items()},
        "pulled_into_eligibility": sum(
            1 for e, p in pairs if e != "eligibility" and p == "eligibility"),
        "refusal_recall": (sum(preds[q["id"]]["intent"] == "out_of_scope" for q in oos)
                           / len(oos)) if oos else None,
        "false_refusals": sum(preds[q["id"]]["intent"] == "out_of_scope" for q in in_scope),
        "scope_reason_accuracy": len(scope_ok) / len(oos) if oos else None,
        "traps_passed": sum(preds[q["id"]]["intent"] == q["intent"] for q in questions if q.get("trap")),
        "traps_total": sum(1 for q in questions if q.get("trap")),
        "errors": sum(p == ERROR for _, p in pairs),
    }


# ------------------------------------------------------------------ main

def run_once(questions: list[dict]) -> dict[str, dict]:
    preds = {}
    for q in questions:
        try:
            r = classify(q["question"])
            preds[q["id"]] = dict(r)
        except RouteError as exc:
            preds[q["id"]] = {"intent": ERROR, "scope_reason": "none", "rationale": str(exc)}
        print(".", end="", flush=True)
    print()
    return preds


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1, help="repeat to check stability")
    ap.add_argument("--questions", type=Path, default=QUESTIONS, help="question file")
    ap.add_argument("--save", type=Path)
    args = ap.parse_args()

    questions = yaml.safe_load(args.questions.read_text())
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids)), "duplicate question ids"
    assert all(q["intent"] in INTENTS for q in questions), "unknown intent in labels"

    print(f"{args.questions.name}: {len(questions)} questions · {ROUTER_MODEL} · prompt {PROMPT_VERSION} · {args.runs} run(s)")
    runs = [run_once(questions) for _ in range(args.runs)]
    preds = runs[0]
    s = score(questions, preds)

    order = list(INTENTS) + [ERROR]
    width = 14
    print("\nexpected ↓ / routed →".ljust(width + 8) + "".join(f"{i[:12]:>{width}}" for i in order))
    for intent in INTENTS:
        row = s["matrix"].get(intent, {})
        print(f"{intent:<{width + 8}}" + "".join(f"{row.get(p, 0) or '·':>{width}}" for p in order))

    print(f"\naccuracy               {s['accuracy']:.0%}")
    for intent in INTENTS:
        r = s["recall"][intent]
        print(f"  recall {intent:<15} {'—' if r is None else f'{r:.0%}'}")
    print(f"pulled into eligibility {s['pulled_into_eligibility']}")
    print(f"refusal recall          {s['refusal_recall']:.0%}   "
          f"false refusals {s['false_refusals']}   "
          f"scope reason right {s['scope_reason_accuracy']:.0%}")
    print(f"traps passed            {s['traps_passed']}/{s['traps_total']}")
    if s["errors"]:
        print(f"ERRORS                  {s['errors']}")

    misses = [q for q in questions if preds[q["id"]]["intent"] != q["intent"]]
    if misses:
        print("\nmisroutes:")
        for q in misses:
            p = preds[q["id"]]
            print(f"  {q['id']:<24} expected {q['intent']:<13} got {p['intent']}")
            print(f"      {q['question']}")
            print(f"      why: {p['rationale']}")

    if args.runs > 1:
        unstable = [qid for qid in ids if len({r[qid]["intent"] for r in runs}) > 1]
        print(f"\nunstable across {args.runs} runs: {len(unstable)}"
              + (f" — {', '.join(unstable)}" if unstable else ""))

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps({
            "questions": args.questions.name,
            "model": ROUTER_MODEL, "prompt_version": PROMPT_VERSION,
            "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "score": s, "runs": runs,
        }, indent=2))
        print(f"\nsaved {args.save}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
