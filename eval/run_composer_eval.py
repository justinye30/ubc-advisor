"""Measure the composer on fixed handler results.

Bypasses routing and extraction: each case builds its entities directly and
runs the real handler, so every answer is composed from real calendar data.
Reports how each answer was produced and how far it drifted from its facts.
Nothing is scored by a model; read the answers with --show.

Run:  python -m eval.run_composer_eval [--show] [--runs 3] [--save PATH]
"""

import argparse
import json
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from agent.checks import drift
from agent.composer import COMPOSER_MODEL, compose
from agent.entities import Entities, catalogue
from agent.handlers import HANDLERS
from agent.router import Route
from core.transcript import Transcript

load_dotenv()
CASES = Path(__file__).parent / "composer_cases.yaml"


def entities_for(case: dict) -> Entities:
    t = Transcript.parse(case.get("have", ""))
    return Entities(
        targets=case.get("targets", []),
        completed=sorted(t.completed),
        grades=dict(t.grades),
        grade_ranges={k: list(v) for k, v in t.grade_ranges.items()},
        in_progress=case.get("in_progress", []),
        year=case.get("year"),
        programs=[],
        transcript_given="have" in case or bool(case.get("in_progress")),
        ambiguous=[], assumptions=case.get("assumptions", []), rejected=[], unused=[],
    )


def check_cases(cases: list[dict], cat: set[str]) -> list[str]:
    bad = []
    for c in cases:
        if c["intent"] not in HANDLERS:
            bad.append(f"{c['id']}: unknown intent {c['intent']}")
        e = entities_for(c)
        for code in [*e["targets"], *e["completed"], *e["in_progress"]]:
            if code not in cat:
                bad.append(f"{c['id']}: {code} is not in courses")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="print every answer")
    ap.add_argument("--runs", type=int, default=1, help="compose each case N times")
    ap.add_argument("--save", type=Path)
    args = ap.parse_args()

    cases = yaml.safe_load(CASES.read_text())
    bad = check_cases(cases, set(catalogue()))
    if bad:
        print("CASE ERRORS:\n" + "\n".join(f"  {b}" for b in bad))
        return 2

    print(f"{len(cases)} cases · {COMPOSER_MODEL} · {args.runs} run(s)\n")
    print(f"{'case':<24}{'by':<16}{'sent':>5}{'words':>7}  drift")
    records = []
    totals = {"advice": 0, "ungrounded_codes": 0, "ungrounded_numbers": 0,
              "ungrounded_remedies": 0, "verdict_conflicts": 0}
    by: dict[str, int] = {}

    for case in cases:
        state = {"question": case["question"],
                 "route": Route(intent=case["intent"], scope_reason="none", rationale="eval"),
                 "entities": entities_for(case)}
        result = HANDLERS[case["intent"]](state)["result"]

        runs = []
        for run in range(args.runs):
            answer = compose(case["question"], result)
            body = " ".join(s["text"] for s in answer["sentences"])
            d = drift(result, answer["facts"], body)
            runs.append((answer, d))
            by[answer["composed_by"]] = by.get(answer["composed_by"], 0) + 1
            for k, v in d.items():
                totals[k] += len(v)
            if args.show:
                tag = f"{case['id']} (run {run + 1})" if args.runs > 1 else case["id"]
                print(f"  ── {tag}")
                print(textwrap.indent(answer["text"], "      │ "))
                for p in answer["problems"]:
                    print(f"      problem: {p}")
                for k, v in d.items():
                    if v:
                        print(f"      DRIFT {k}: {', '.join(v)}")
                print()

        drifted = [d for _, d in runs if any(d.values())]
        first = drifted[0] if drifted else {}
        flags = "; ".join(f"{k}: {', '.join(v)}" for k, v in first.items() if v) or "—"
        if args.runs > 1 and drifted:
            flags = f"{len(drifted)}/{args.runs} runs — {flags}"
        answers = [a for a, _ in runs]
        kinds = sorted({a["composed_by"] for a in answers})
        retried = sum(1 for a in answers if a["problems"] and a["composed_by"] == "llm")
        label = "/".join(kinds) + (f" ({retried} retried)" if retried else "")
        sents = sum(len(a["sentences"]) for a in answers) / len(answers)
        words = sum(len(" ".join(x["text"] for x in a["sentences"]).split()) for a in answers) / len(answers)
        if not args.show:
            print(f"{case['id']:<24}{label:<16}{sents:>5.0f}{words:>7.0f}  {flags}")
        records.append({"id": case["id"], "status": result.get("status"),
                        "runs": [{"answer": a, "drift": d} for a, d in runs]})

    print("\ncomposed by: " + ", ".join(f"{k} {v}" for k, v in sorted(by.items())))
    print("drift:       " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in totals.items()))
    n_drift = sum(any(any(r["drift"].values()) for r in rec["runs"]) for rec in records)
    print(f"cases with drift in any run: {n_drift}/{len(records)}")

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps({
            "model": COMPOSER_MODEL,
            "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "runs": args.runs, "composed_by": by, "totals": totals, "records": records,
        }, indent=2, default=str))
        print(f"saved {args.save}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
