"""Ask a question in plain English and see how it's routed and handled.

  python -m agent "can I retake a course I passed?"
  python -m agent --route-only "should I take CPSC 320 or 322?"
  python -m agent --graph          # print the graph as Mermaid

This is a debug view: it prints the structured result a handler produced.
Turning that into a sentence is the composer's job (Step 14).
"""

import argparse
import sys
import textwrap

from dotenv import load_dotenv

load_dotenv()

from agent.graph import ask, get_app
from agent.router import PROMPT_VERSION, ROUTER_MODEL, classify


def show_result(result: dict) -> None:
    kind, status = result.get("kind"), result.get("status")
    print(f"  handler: {kind}   status: {status}")
    if result.get("codes"):
        print(f"  codes:   {', '.join(result['codes'])}")

    if status in ("needs_course", "course_not_found"):
        what = "that course isn't in my data" if status == "course_not_found" else "no course code found"
        print(f"\n  {what}. (Full codes only until entity extraction — e.g. 'CPSC 221'.)")
        return

    if kind == "eligibility":
        for c in result.get("courses", []):
            if not c["found"]:
                print(f"\n  {c['code']}: not in my data")
                continue
            print(f"\n  {c['code']} — {c['title']}")
            print(textwrap.fill(c["prereq_text"] or "(no prerequisites listed)", 74,
                                initial_indent="    ", subsequent_indent="    "))
            print(f"    {c['source_url']}")
    elif kind == "policy":
        for i, h in enumerate(result.get("hits", []), start=1):
            print(f"\n  {i}. [{h['score']:.4f}] {h['section_path']}")
    elif kind == "unlock":
        print(f"\n  required by ({len(result['required_by'])}): {', '.join(result['required_by'])}")
        print(f"  one option for ({len(result['option_for'])}): {', '.join(result['option_for'])}")
    elif kind == "path":
        print()
        for line in result.get("tree", []):
            print(f"    {line}")
        print(f"\n  required on every route: {', '.join(result['required_on_every_route']) or '—'}")
    elif kind in ("out_of_scope", "error"):
        print(f"\n  {result['message']}")


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m agent")
    ap.add_argument("question", nargs="?")
    ap.add_argument("--route-only", action="store_true", help="classify, don't run a handler")
    ap.add_argument("--graph", action="store_true", help="print the graph as Mermaid")
    args = ap.parse_args()

    if args.graph:
        print(get_app().get_graph().draw_mermaid())
        return 0
    if not args.question:
        ap.error("a question is required")

    print(f"\n  router: {ROUTER_MODEL}  prompt {PROMPT_VERSION}")
    if args.route_only:
        route = classify(args.question)
        print(f"  intent:  {route['intent']}"
              + (f" ({route['scope_reason']})" if route["intent"] == "out_of_scope" else ""))
        print(f"  why:     {route['rationale']}\n")
        return 0

    state = ask(args.question)
    route = state.get("route")
    if route:
        print(f"  intent:  {route['intent']}"
              + (f" ({route['scope_reason']})" if route["intent"] == "out_of_scope" else ""))
        print(f"  why:     {route['rationale']}")
    show_result(state.get("result", {}))
    print()
    return 0 if state.get("result", {}).get("status") != "error" else 1


if __name__ == "__main__":
    sys.exit(main())
