"""End-to-end eval: 50 questions through the whole pipeline.

Three numbers, reported separately (Week 2 plan, Step 16):
  routing accuracy     did the question reach the right handler?
  answer correctness   on the 40 answerable: right route, and the handler
                       result the pipeline reached from the English question
                       matches the result for the gold inputs, and the
                       answer passes its text checks
  refusal correctness  on the 10 unanswerable: did it decline?

Plus: false refusals, guard actions (and every sentence the guard caught, to
read by hand), and latency.

Run:  python -m eval.run_e2e_eval [--show] [--only q01,q15] [--save PATH]
      python -m eval.run_e2e_eval --audit     # gold results + calendar text, no API calls
"""

import argparse
import json
import re
import statistics
import sys
import textwrap
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from agent.entities import catalogue
from agent.graph import get_app, pipeline_version
from agent.handlers import HANDLERS
from agent.router import Route
from core.repo import get_course
from eval.run_composer_eval import entities_for

load_dotenv()
QUESTIONS = Path(__file__).parent / "e2e_questions.yaml"

DECLINE_STATUSES = {"refused", "course_not_found", "no_results", "needs_course"}
SAYS_NOT_COVERED = re.compile(
    r"(?:don't|do not|doesn't|does not) (?:address|cover|say|mention|include|specify|list)"
    r"|not (?:covered|addressed|mentioned|specified)|isn't (?:covered|addressed|mentioned)"
    r"|(?:couldn't|could not|can't|cannot) find|no (?:information|section)", re.IGNORECASE)


# ------------------------------------------------------------------ scoring (pure)

def _codes(items: list) -> list[str]:
    return [i["code"] if isinstance(i, dict) else i for i in items]


def result_mismatches(gold: dict, got: dict) -> list[str]:
    """Where the pipeline's handler result differs from the gold-input result."""
    if gold.get("status") != got.get("status"):
        return [f"status {got.get('status')}, expected {gold.get('status')}"]
    out: list[str] = []

    def diff(name: str, want, have) -> None:
        if set(want) != set(have):
            out.append(f"{name}: got {sorted(set(have))}, expected {sorted(set(want))}")

    diff("courses", gold.get("codes", []), got.get("codes", []))
    kind, status = gold.get("kind"), gold.get("status")
    if kind == "eligibility" and status in ("evaluated", "requirements_only"):
        diff("verdicts", [f"{c['code']}={c.get('verdict', '-')}" for c in gold["courses"]],
             [f"{c['code']}={c.get('verdict', '-')}" for c in got["courses"]])
    elif kind == "eligibility" and status == "sweep":
        diff("eligible", gold["eligible"], got["eligible"])
        diff("to confirm", _codes(gold["to_confirm"]), _codes(got["to_confirm"]))
    elif kind == "unlock" and status == "ok":
        diff("required by", gold["required_by"], got["required_by"])
        diff("option for", gold["option_for"], got["option_for"])
    elif kind == "unlock" and status == "personal":
        diff("newly eligible", gold["newly_eligible"], got["newly_eligible"])
        diff("still to confirm", _codes(gold["to_confirm"]), _codes(got["to_confirm"]))
    elif kind == "path" and status == "ok":
        diff("verdict", [gold.get("verdict") or "-"], [got.get("verdict") or "-"])
        diff("required on every route", gold["required_on_every_route"],
             got["required_on_every_route"])
        diff("ready now", gold["ready_now"], got["ready_now"])
    return out


def text_failures(case: dict, answer: dict | None) -> list[str]:
    if not answer:
        return ["no answer"]
    out = []
    text = answer["text"].lower()
    for phrase in case.get("mentions", []):
        if not any(alt.strip().lower() in text for alt in phrase.split("|")):
            out.append(f"doesn't mention '{phrase}'")
    pages = case.get("pages")
    if pages:
        urls = [s["url"].rstrip("/") for s in answer.get("sources", [])]
        if not any(u.endswith("/" + p) for u in urls for p in pages):
            out.append(f"cites none of {pages}")
    if answer.get("guard", {}).get("remaining"):
        out.append("guard left violations")
    return out


def clarify_failures(case: dict, result: dict) -> list[str]:
    if result.get("status") != "needs_clarification":
        return []          # the status check reports this
    offered = {c for a in result.get("ambiguous", []) for c in a["candidates"]}
    missing = [c for c in case.get("candidates", []) if c not in offered]
    return [f"didn't offer {missing}"] if missing else []


def declined(result: dict, answer: dict | None) -> str | None:
    """How the system declined, or None if it answered."""
    status = result.get("status")
    if status in DECLINE_STATUSES:
        return status
    body = " ".join(s["text"] for s in (answer or {}).get("sentences", []))
    if SAYS_NOT_COVERED.search(body):
        return "said the calendar doesn't cover it"
    return None


def score_answerable(case: dict, route: dict | None, result: dict,
                     answer: dict | None, gold: dict | None) -> list[str]:
    if route is None:
        return ["routing failed"]
    fails = []
    if route["intent"] != case["intent"]:
        fails.append(f"routed to {route['intent']}")
    expected = case.get("status")
    if expected and result.get("status") != expected:
        fails.append(f"status {result.get('status')}, expected {expected}")
    if expected == "needs_clarification":
        fails += clarify_failures(case, result)
    elif gold is not None and not fails:
        fails += result_mismatches(gold, result)
    if result.get("status") in DECLINE_STATUSES:
        fails.append(f"declined ({result.get('status')})")
    fails += text_failures(case, answer)
    return fails


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p * (len(ordered) - 1)))]


# ------------------------------------------------------------------ runner

def gold_result(case: dict) -> dict | None:
    if case.get("decline") or case["intent"] == "policy" or case.get("status") == "needs_clarification":
        return None
    state = {"question": case["question"],
             "route": Route(intent=case["intent"], scope_reason="none", rationale="gold"),
             "entities": entities_for(case)}
    return HANDLERS[case["intent"]](state)["result"]


def check_labels(cases: list[dict], cat: set[str]) -> list[str]:
    bad = []
    for c in cases:
        if c.get("decline"):
            continue
        e = entities_for(c)
        for code in [*e["targets"], *e["completed"], *e["in_progress"], *c.get("candidates", [])]:
            if code not in cat:
                bad.append(f"{c['id']}: {code} is not in courses")
    return bad


def audit(cases: list[dict]) -> int:
    """Print gold results next to the calendar text, to check the core by hand."""
    for c in cases:
        gold = gold_result(c)
        if gold is None:
            continue
        print(f"\n## {c['id']}  {c['question']}")
        print(f"   gold inputs: targets {c.get('targets', [])}  have [{c.get('have', '')}]"
              f"  in progress {c.get('in_progress', [])}  year {c.get('year')}")
        for code in c.get("targets", []):
            course = get_course(code)
            if course:
                print(f"   {code} calendar: {course.prereq_text or '(no prerequisites listed)'}")
        status = gold.get("status")
        if gold["kind"] == "eligibility" and status in ("evaluated", "requirements_only"):
            for x in gold["courses"]:
                print(f"   → {x['code']}: {x.get('verdict', '(no verdict: no history)')}")
                for r in x.get("reasons", []):
                    print(f"       [{r['state']}] {r['text']}")
        elif status == "sweep":
            print(f"   → prerequisites met ({gold['counts']['eligible']}): "
                  f"{', '.join(gold['eligible']) or '—'}")
            print(f"   → no listed prerequisites ({gold['counts']['no_prereq']}): "
                  f"{', '.join(gold['no_prereq']) or '—'}")
            print(f"   → can't tell yet: {gold['counts']['to_confirm']}; "
                  f"not yet: {gold['counts']['not_yet']}")
        elif gold["kind"] == "unlock":
            for key in ("required_by", "option_for", "newly_eligible", "already_eligible"):
                if key in gold:
                    print(f"   → {key.replace('_', ' ')}: {', '.join(gold[key]) or '—'}")
        elif gold["kind"] == "path":
            print(f"   → verdict {gold.get('verdict')}; required on every route: "
                  f"{', '.join(gold['required_on_every_route']) or '—'}; "
                  f"ready now: {', '.join(gold['ready_now']) or '—'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="print every answer")
    ap.add_argument("--only", help="comma-separated question ids")
    ap.add_argument("--save", type=Path)
    ap.add_argument("--audit", action="store_true", help="print gold results; no API calls")
    args = ap.parse_args()

    cases = yaml.safe_load(QUESTIONS.read_text())
    bad = check_labels(cases, set(catalogue()))
    if bad:
        print("LABEL ERRORS — fix these before trusting any number:\n")
        print("\n".join(f"  {b}" for b in bad))
        return 2
    if args.audit:
        return audit(cases)
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]

    version = pipeline_version()
    print(f"{len(cases)} questions · pipeline {version}\n")
    print(f"{'id':<5}{'route':<14}{'status':<22}{'guard':<13}{'secs':>6}  result")
    app = get_app()
    rows = []

    for case in cases:
        started = time.monotonic()
        state: dict[str, Any]
        try:
            state = app.invoke({"question": case["question"]})
        except Exception as exc:  # noqa: BLE001 — one broken question mustn't end the run
            state = {"result": {"status": "crashed", "message": f"{type(exc).__name__}: {exc}"}}
        secs = time.monotonic() - started
        route, result, answer = state.get("route"), state.get("result", {}), state.get("answer")

        if result.get("status") == "crashed":
            fails, note, verdict = ["CRASHED"], "", "CRASHED: " + result["message"]
        elif case.get("decline"):
            how = declined(result, answer)
            fails = [] if how else ["answered instead of declining"]
            if case.get("intent") and route and route["intent"] != case["intent"]:
                note = f"routed to {route['intent']}"
            else:
                note = ""
            verdict = f"declined: {how}" if how else "ANSWERED"
        else:
            fails = score_answerable(case, route, result, answer, gold_result(case))
            note = ""
            verdict = "ok" if not fails else "; ".join(fails)

        routed = route["intent"] if route else "—"
        route_ok = case.get("intent") is None or (route is not None and route["intent"] == case["intent"])
        guard_action = (answer or {}).get("guard", {}).get("action", "—")
        print(f"{case['id']:<5}{routed + ('' if route_ok else ' ✗'):<14}"
              f"{result.get('status')!s:<22}{guard_action:<13}{secs:>6.1f}  "
              f"{verdict}{('  (' + note + ')') if note else ''}")
        if args.show and answer:
            print(textwrap.indent(answer["text"], "        │ "))
            print()
        rows.append({"id": case["id"], "question": case["question"], "decline": bool(case.get("decline")),
                     "expected_intent": case.get("intent"), "route": route, "status": result.get("status"),
                     "route_ok": route_ok, "fails": fails, "secs": round(secs, 2),
                     "answer": answer, "result": result})

    labelled = [r for r in rows if r["expected_intent"]]
    answerable = [r for r in rows if not r["decline"]]
    unanswerable = [r for r in rows if r["decline"]]
    false_refusals = [r for r in answerable if r["status"] in DECLINE_STATUSES]
    actions: dict[str, int] = {}
    for r in rows:
        a = (r["answer"] or {}).get("guard", {}).get("action", "none")
        actions[a] = actions.get(a, 0) + 1
    secs = [r["secs"] for r in rows]

    print(f"\npipeline {version}")
    print(f"routing accuracy     {sum(r['route_ok'] for r in labelled)}/{len(labelled)}")
    print(f"answer correctness   {sum(not r['fails'] for r in answerable)}/{len(answerable)}")
    print(f"refusal correctness  {sum(not r['fails'] for r in unanswerable)}/{len(unanswerable)}")
    print(f"false refusals       {len(false_refusals)}")
    print("guard                " + ", ".join(f"{k} {v}" for k, v in sorted(actions.items())))
    if secs:
        print(f"latency              p50 {statistics.median(secs):.1f}s  "
              f"p95 {percentile(secs, 0.95):.1f}s  max {max(secs):.1f}s")

    caught = [(r["id"], c) for r in rows for c in (r["answer"] or {}).get("guard", {}).get("caught", [])]
    if caught:
        print("\nsentences the guard caught (read these — is each a real problem?):")
        for qid, c in caught:
            print(f"  {qid}: {c['sentence']}")
            for why in c["why"]:
                print(f"        → {why}")

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps({
            "pipeline": version, "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "rows": rows,
        }, indent=2, default=str))
        print(f"\nsaved {args.save}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
