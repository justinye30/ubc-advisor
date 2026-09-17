"""Measure the composer and the citation guard on fixed handler results.

Bypasses routing and extraction: each case builds its entities directly and
runs the real handler, so every answer is composed from real calendar data.
For each answer: what the guard found in the first draft, what it did
(passed / regenerated / trimmed / fallback), and a final re-check that must
come back clean. Nothing is scored by a model; read the answers with --show.

Run:  python -m eval.run_composer_eval [--show] [--runs 3] [--save PATH]
      python -m eval.run_composer_eval --rescore eval/results/composer_baseline.json
          # apply today's guard checks to saved answers — no API calls
"""

import argparse
import json
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from agent.composer import COMPOSER_MODEL, Answer, compose
from agent.entities import Entities, catalogue
from agent.guard import check_answer, guard, violation_kind
from agent.handlers import HANDLERS
from agent.present import build_facts
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


def result_for(case: dict) -> dict:
    state = {"question": case["question"],
             "route": Route(intent=case["intent"], scope_reason="none", rationale="eval"),
             "entities": entities_for(case)}
    return HANDLERS[case["intent"]](state)["result"]


def show_answer(tag: str, answer: Answer, caught: dict[int, list[str]]) -> None:
    print(f"  ── {tag}")
    print(textwrap.indent(answer["text"], "      │ "))
    g = answer.get("guard", {})
    if g:
        print(f"      guard: {g['action']}")
    for i, msgs in sorted(caught.items()):
        print(f"      caught in draft, sentence {i + 1}: {'; '.join(msgs)}")
    print()


def rescore(path: Path, cases: list[dict]) -> int:
    """Apply the current checks to answers saved by an earlier run."""
    saved = json.loads(path.read_text())
    by_id = {c["id"]: c for c in cases}
    flagged = total = 0
    for rec in saved["records"]:
        case = by_id.get(rec["id"])
        if case is None:
            continue
        result = result_for(case)
        facts = build_facts(case["question"], result)
        for n, run in enumerate(rec["runs"], start=1):
            saved_answer = run.get("answer") or run["draft"]     # Step 14 files / guarded files
            found = check_answer(saved_answer, result, facts)
            total += len(saved_answer["sentences"])
            for i, msgs in sorted(found.items()):
                flagged += 1
                print(f"{rec['id']} run {n}, sentence {i + 1}: {saved_answer['sentences'][i]['text']}")
                for m in msgs:
                    print(f"    → {m}")
    print(f"\n{flagged} of {total} saved sentences flagged by the current guard")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="print every answer")
    ap.add_argument("--runs", type=int, default=1, help="compose each case N times")
    ap.add_argument("--save", type=Path)
    ap.add_argument("--rescore", type=Path, help="check saved answers instead of composing")
    args = ap.parse_args()

    cases = yaml.safe_load(CASES.read_text())
    bad = check_cases(cases, set(catalogue()))
    if bad:
        print("CASE ERRORS:\n" + "\n".join(f"  {b}" for b in bad))
        return 2
    if args.rescore:
        return rescore(args.rescore, cases)

    print(f"{len(cases)} cases · {COMPOSER_MODEL} · {args.runs} run(s)\n")
    print(f"{'case':<24}{'caught in drafts':<18}{'guard actions':<30}after")
    records = []
    actions: dict[str, int] = {}
    kinds: dict[str, int] = {}
    caught_total = leaked = 0

    for case in cases:
        result = result_for(case)
        facts = build_facts(case["question"], result)
        runs = []
        for run in range(args.runs):
            draft = compose(case["question"], result)
            caught = check_answer(draft, result, facts)
            final = guard(case["question"], result, draft)
            remaining = check_answer(final, result, facts)
            action = final.get("guard", {}).get("action", "?")
            actions[action] = actions.get(action, 0) + 1
            caught_total += len(caught)
            leaked += len(remaining)
            for msgs in caught.values():
                for m in msgs:
                    kinds[violation_kind(m)] = kinds.get(violation_kind(m), 0) + 1
            runs.append({"draft": draft, "caught": caught, "final": final, "remaining": remaining})
            if args.show:
                show_answer(f"{case['id']} (run {run + 1})" if args.runs > 1 else case["id"],
                            final, caught)

        n_caught = sum(1 for r in runs if r["caught"])
        acts = ", ".join(f"{a} {c}" for a, c in sorted(
            {a: sum(1 for r in runs if r["final"].get("guard", {}).get("action") == a)
             for a in {r["final"].get("guard", {}).get("action") for r in runs}}.items()))
        n_left = sum(len(r["remaining"]) for r in runs)
        if not args.show:
            print(f"{case['id']:<24}{f'{n_caught}/{args.runs} runs':<18}{acts:<30}"
                  f"{'clean' if not n_left else f'{n_left} LEFT'}")
        records.append({"id": case["id"], "status": result.get("status"), "runs": runs})

    print("\nguard actions: " + ", ".join(f"{a} {c}" for a, c in sorted(actions.items())))
    print(f"sentences caught in drafts: {caught_total}")
    if kinds:
        print("violations by kind: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    print(f"violations left after the guard: {leaked}")

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps({
            "model": COMPOSER_MODEL,
            "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "runs": args.runs, "actions": actions, "caught": caught_total, "leaked": leaked,
            "records": records,
        }, indent=2, default=str))
        print(f"saved {args.save}")
    print()
    return 1 if leaked else 0


if __name__ == "__main__":
    sys.exit(main())
