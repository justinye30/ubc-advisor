"""Ask a question in plain English.

  python -m agent "can I retake a course I passed?"
  python -m agent --debug "can I take 221? I did 110, 121 and 210"
  python -m agent --route-only "should I take CPSC 320 or 322?"
  python -m agent --graph          # print the graph as Mermaid

By default this prints the composed answer. --debug adds the route, the
structured result the handler produced, and how the answer was composed.
"""

import argparse
import sys
import textwrap

from dotenv import load_dotenv

load_dotenv()

from agent.graph import ask, get_app
from agent.router import PROMPT_VERSION, ROUTER_MODEL, classify


def _wrap(text: str, indent: str = "    ") -> str:
    return textwrap.fill(text, 76, initial_indent=indent, subsequent_indent=indent)


def show_context(ctx: dict) -> None:
    if not ctx:
        return
    done = [f"{c} ({ctx['grades'][c]})" if c in ctx["grades"] else c for c in ctx["completed"]]
    if ctx["transcript_given"]:
        print(f"  history: {', '.join(done) or 'nothing completed'}"
              + (f"; in progress {', '.join(ctx['in_progress'])}" if ctx["in_progress"] else ""))
    else:
        print("  history: not given")
    if ctx["year"] or ctx["programs"]:
        print(f"  student: year {ctx['year'] or '?'}"
              + (f", {', '.join(ctx['programs'])}" if ctx["programs"] else ""))
    for note in ctx["assumptions"]:
        print(f"  assumed: {note}")
    for note in ctx["ignored"]:
        print(f"  ignored: {note}")


def show_result(result: dict) -> None:
    kind, status = result.get("kind"), result.get("status")
    print(f"  handler: {kind}   status: {status}")
    if result.get("codes"):
        print(f"  codes:   {', '.join(result['codes'])}")
    show_context(result.get("context", {}))

    if status in ("needs_course", "course_not_found", "needs_clarification"):
        text = {
            "needs_course": "Which course do you mean? Tell me its code, e.g. CPSC 221.",
            "course_not_found": "That course isn't in my data.",
        }.get(status, result.get("message", ""))
        print(f"\n  {text}")
        return

    if kind == "eligibility" and status == "sweep":
        c = result["counts"]
        print(f"\n  subjects: {', '.join(result['subjects'])}")
        print(f"  eligible ({c['eligible']}): {', '.join(result['eligible'])}")
        print(f"  no listed prerequisites ({c['no_prereq']}): {', '.join(result['no_prereq'])}")
        print(f"  to confirm ({c['to_confirm']}):")
        for item in result["to_confirm"][:8]:
            print(f"    {item['code']}: {item['summary']}")
        print(f"  not yet: {c['not_yet']}")
    elif kind == "eligibility":
        for c in result.get("courses", []):
            if not c["found"]:
                print(f"\n  {c['code']}: not in my data")
                continue
            print(f"\n  {c['code']} — {c['title']}")
            if c.get("verdict"):
                print(f"    verdict: {c['verdict']}" + (f" — {c['summary']}" if c.get("summary") else ""))
                for r in c.get("reasons", []):
                    print(f"      [{r['state']}] {r['text']}")
            print(_wrap(c["prereq_text"] or "(no prerequisites listed)"))
            print(f"    {c['source_url']}")
    elif kind == "policy":
        for i, h in enumerate(result.get("hits", []), start=1):
            print(f"\n  {i}. [{h['score']:.4f}] {h['section_path']}")
    elif kind == "unlock" and status == "personal":
        print(f"\n  newly eligible: {', '.join(result['newly_eligible']) or '—'}")
        for label in ("to_confirm", "still_blocked"):
            print(f"  {label.replace('_', ' ')}:")
            for item in result[label]:
                print(f"    {item['code']}: {item['summary']}")
        print(f"  already eligible without it: {', '.join(result['already_eligible']) or '—'}")
    elif kind == "unlock":
        print(f"\n  required by ({len(result['required_by'])}): {', '.join(result['required_by'])}")
        print(f"  one option for ({len(result['option_for'])}): {', '.join(result['option_for'])}")
    elif kind == "path":
        if result.get("verdict"):
            print(f"  right now: {result['verdict']}")
        print()
        for line in result.get("tree", []):
            print(f"    {line}")
        print(f"\n  required on every route: {', '.join(result['required_on_every_route']) or '—'}")
        print(f"  ready to take now: {', '.join(result['ready_now']) or '—'}")
    elif kind in ("out_of_scope", "error"):
        print(f"\n  {result['message']}")


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m agent")
    ap.add_argument("question", nargs="?")
    ap.add_argument("--route-only", action="store_true", help="classify, don't run a handler")
    ap.add_argument("--debug", action="store_true", help="show route, result, and composition")
    ap.add_argument("--graph", action="store_true", help="print the graph as Mermaid")
    args = ap.parse_args()

    if args.graph:
        print(get_app().get_graph().draw_mermaid())
        return 0
    if not args.question:
        ap.error("a question is required")

    if args.route_only:
        print(f"\n  router: {ROUTER_MODEL}  prompt {PROMPT_VERSION}")
        route = classify(args.question)
        print(f"  intent:  {route['intent']}"
              + (f" ({route['scope_reason']})" if route["intent"] == "out_of_scope" else ""))
        print(f"  why:     {route['rationale']}\n")
        return 0

    state = ask(args.question)
    answer = state.get("answer")

    if args.debug:
        print(f"\n  router: {ROUTER_MODEL}  prompt {PROMPT_VERSION}")
        route = state.get("route")
        if route:
            print(f"  intent:  {route['intent']}"
                  + (f" ({route['scope_reason']})" if route["intent"] == "out_of_scope" else ""))
            print(f"  why:     {route['rationale']}")
        show_result(state.get("result", {}))
        if answer:
            print(f"\n  composed by: {answer['composed_by']}")
            for p in answer["problems"]:
                print(f"  problem:     {p}")
            for s in answer["sentences"]:
                print(f"    [{', '.join(s['cites'])}] {s['text']}")
        print("\n" + "-" * 76)

    if answer:
        print()
        for para in answer["text"].split("\n\n"):
            print("\n".join(_wrap(line, "") for line in para.split("\n")))
            print()
    return 0 if state.get("result", {}).get("status") != "error" else 1


if __name__ == "__main__":
    sys.exit(main())
