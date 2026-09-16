"""Command-line interface for prerequisite checking.

  check    — can I take one course, and if not, what's missing
  sweep    — what am I eligible for
  unlocks  — what does a course lead to
  path     — what lies between me and a course

This is presentation only. All logic lives in core.evaluator and core.graph.
"""
import argparse
import sys

from core.codes import OutOfScope, course_url, normalize
from core.evaluator import INDETERMINATE, NOT_SATISFIED, SATISFIED, evaluate
from core.repo import Course, get_course, list_courses, suggest_codes
from core.transcript import Transcript
from core.graph import PathView, always_required, ancestry, connect, dependents, unlocks_for

DISCLAIMER = (
    "Unofficial. Prerequisites may be waived at instructor discretion; the "
    "UBC Academic Calendar is authoritative. Confirm with an advisor."
)

MARK = {SATISFIED: "✓", NOT_SATISFIED: "✗", INDETERMINATE: "?"}

VERDICT = {
    SATISFIED: "You meet the listed prerequisites.",
    NOT_SATISFIED: "You do not meet the listed prerequisites.",
    INDETERMINATE: "Can't determine from what you've told me.",
}


def build_transcript(args) -> Transcript:
    return Transcript.parse(
        args.have or "",
        year=args.year,
        programs={p.strip() for p in args.program.split(",")} if args.program else None,
    )


def resolve(raw: str) -> str:
    """Normalize a user-typed course code, exiting with help on failure."""
    try:
        return normalize(raw)
    except OutOfScope:
        sys.exit(f"'{raw}' is an Okanagan course. This tool covers Vancouver only.")
    except ValueError:
        sys.exit(f"'{raw}' doesn't look like a course code. Try e.g. 'CPSC 221'.")


def wrap(text: str, width: int = 74, indent: str = "  ") -> str:
    import textwrap
    return textwrap.fill(text, width, initial_indent=indent, subsequent_indent=indent)


# ---------------------------------------------------------------- check

def cmd_check(args) -> int:
    code = resolve(args.want)
    course = get_course(code)

    if course is None:
        hint = suggest_codes(code)
        msg = f"{code} isn't in my data."
        if hint:
            msg += f" Did you mean: {', '.join(hint)}?"
        sys.exit(msg)

    t = build_transcript(args)

    print()
    title = f"{course.code}" + (f" — {course.title}" if course.title else "")
    print(title)
    print("=" * min(len(title), 74))

    if course.prereq_tree is None:
        if course.extraction_status == "no_prereq":
            print("\n  ✓ No prerequisites listed.")
        else:
            print(f"\n  ? Requirements not available "
                  f"(status: {course.extraction_status}).")
        print(f"\n  Calendar: {course.source_url}\n")
        print(wrap(DISCLAIMER))
        return 0

    result = evaluate(course.prereq_tree, t)

    print(f"\n  {MARK[result.state]} {VERDICT[result.state]}")

    if result.state is SATISFIED:
        for reason in result.blocking[:3]:
            print(f"      {reason}")
    else:
        label = "Missing:" if result.state is NOT_SATISFIED else "Need to confirm:"
        print(f"\n  {label}")
        for reason in result.blocking:
            print(f"      • {reason}")
            
        if result.state is INDETERMINATE:
            others = [r.text for r in result.reasons if r.state is NOT_SATISFIED]
            if others:
                print("\n  Also note:")
                for reason in others:
                    print(f"      • {reason}")

    if course.extraction_status == "flagged":
        print("\n  Note: this course's requirements were flagged during parsing.")
        print("        Treat the verdict with extra caution.")

    if course.prereq_text:
        print("\n  Calendar text:")
        print(wrap(course.prereq_text, indent="      "))

    print(f"\n  Source: {course.source_url}\n")
    print(wrap(DISCLAIMER))
    return 0


# ---------------------------------------------------------------- sweep

def cmd_sweep(args) -> int:
    t = build_transcript(args)
    courses = list_courses(subject=args.subject, level_min=args.level)

    buckets: dict = {SATISFIED: [], INDETERMINATE: [], NOT_SATISFIED: []}
    no_prereq: list[Course] = []
    skipped = 0
    graduate = 0

    for course in courses:
        if course.code in t.completed:
            continue

        # Graduate courses (500+) aren't open to undergraduates, but the
        # calendar doesn't encode that as a prerequisite.
        level = int(course.code.split()[1].rstrip("ABCDEFGH"))
        if level >= 500 and not args.graduate:
            graduate += 1
            continue

        if course.prereq_tree is None:
            if course.extraction_status == "no_prereq":
                no_prereq.append(course)
            else:
                skipped += 1
            continue

        result = evaluate(course.prereq_tree, t)
        buckets[result.state].append((course, result))

    def row(mark: str, course: Course, reason: str = "") -> None:
        title = (course.title or "")[:34]
        line = f"  {mark} {course.code:<10} {title:<36}{reason[:26]}"
        print(line.rstrip())

    def section(state, heading: str, show_reason: bool) -> None:
        items = buckets[state]
        if not items:
            return
        print(f"\n{heading} ({len(items)})")
        print("-" * 74)
        for course, result in items:
            row(MARK[state], course)
            if show_reason:
                print(wrap(result.summary, indent="               "))

    print()
    section(SATISFIED, "ELIGIBLE — prerequisites checked and met", False)

    if no_prereq:
        print(f"\nNO LISTED PREREQUISITES ({len(no_prereq)})")
        print("-" * 74)
        print("  Nothing to check. Registration may still be restricted by")
        print("  program, year, or instructor approval.")
        for course in no_prereq:
            row("·", course)

    section(INDETERMINATE, "POSSIBLY ELIGIBLE — needs confirmation", True)
    if args.all:
        section(NOT_SATISFIED, "NOT YET ELIGIBLE", True)

    print(f"\n{len(buckets[SATISFIED])} eligible, "
          f"{len(no_prereq)} with no listed prerequisites, "
          f"{len(buckets[INDETERMINATE])} to confirm, "
          f"{len(buckets[NOT_SATISFIED])} not yet")
    if graduate:
        print(f"{graduate} graduate course(s) hidden — use --graduate to include.")
    if skipped:
        print(f"{skipped} course(s) skipped — requirements not parsed.")
    if not args.all:
        print("Use --all to include courses you're not eligible for.")
    print()
    print(wrap(DISCLAIMER))
    return 0


# ---------------------------------------------------------------- unlocks

def cmd_unlocks(args) -> int:
    code = resolve(args.course)
    course = get_course(code)
    if course is None:
        sys.exit(f"{code} isn't in my data.")

    with connect() as conn:
        deps = dependents(conn, code)

    print()
    title = f"What {code} leads to" + (f" — {course.title}" if course.title else "")
    print(title)
    print("=" * min(len(title), 74))

    if not deps:
        print(f"\n  No course in my data lists {code} as a prerequisite.\n")
        print(wrap(DISCLAIMER))
        return 0

    def row(mark: str, code_: str, title_: str | None, reason: str = "") -> None:
        line = f"  {mark} {code_:<10} {(title_ or '')[:34]:<36}{reason[:26]}"
        print(line.rstrip())

    if not args.have:
        required = [d for d in deps if not d.is_optional]
        optional = [d for d in deps if d.is_optional]
        if required:
            print(f"\nREQUIRES {code} ({len(required)})")
            print("-" * 74)
            for d in required:
                row("·", d.code, d.title)
        if optional:
            print(f"\n{code} IS ONE OPTION ({len(optional)})")
            print("-" * 74)
            print("  Another course could satisfy the same requirement.")
            for d in optional:
                row("·", d.code, d.title)
        print(f"\nAdd --have to see what {code} would open up for you specifically.\n")
        print(wrap(DISCLAIMER))
        return 0

    t = build_transcript(args)
    u = unlocks_for(code, t, deps)

    def section(items, mark: str, heading: str) -> None:
        if not items:
            return
        print(f"\n{heading} ({len(items)})")
        print("-" * 74)
        for d, result in items:
            row(mark, d.code, d.title)
            if mark != "✓":
                print(wrap(result.summary, indent="               "))

    if code in t.completed:
        print(f"\n  You've already completed {code}; showing what it counts toward.")
    section(u.newly_eligible, "✓", f"NEWLY ELIGIBLE after {code}")
    section(u.to_confirm, "?", f"AFTER {code}, NEEDS CONFIRMATION")
    if args.all:
        section(u.still_blocked, "✗", f"STILL BLOCKED after {code}")

    print(f"\n{len(u.newly_eligible)} newly eligible, {len(u.to_confirm)} to confirm, "
          f"{len(u.still_blocked)} still blocked, "
          f"{len(u.already_eligible)} you can already take")
    if not args.all and u.still_blocked:
        print("Use --all to see what else each blocked course needs.")
    print()
    print(wrap(DISCLAIMER))
    return 0


# ---------------------------------------------------------------- path

def cmd_path(args) -> int:
    code = resolve(args.want)
    course = get_course(code)
    if course is None:
        sys.exit(f"{code} isn't in my data.")

    t = build_transcript(args)
    with connect() as conn:
        rows = ancestry(conn, code, stop_at=t.completed)

    print()
    title = f"Path to {code}" + (f" — {course.title}" if course.title else "")
    print(title)
    print("=" * min(len(title), 74))

    if course.prereq_tree is not None:
        result = evaluate(course.prereq_tree, t)
        print(f"\n  Right now: {MARK[result.state]} {VERDICT[result.state]}")

    if not rows:
        if course.extraction_status == "no_prereq":
            print("\n  No prerequisites listed.")
        else:
            print(f"\n  No course prerequisites in my data (status: {course.extraction_status}).")
        print()
        print(wrap(DISCLAIMER))
        return 0

    view = PathView(code, course.prereq_tree, rows, t)
    print(f"\n  {code}")
    for line in view.render():
        print(f"  {line}")

    todo = [c for c in always_required(code, rows, stop_at=t.completed | view.ready())
            if c not in t.completed]
    print("\n  ✓ completed   → ready to take   · not yet   ? can't check from our data")
    print("  Only what still stands between you and the course is shown.")
    if view.hidden_okanagan:
        print(f"  {view.hidden_okanagan} Okanagan alternative(s) not shown.")
    if todo:
        print(f"\n  Required on every route: {', '.join(todo)}")
    else:
        print("\n  Nothing here is required on every route — each step has alternatives.")
    print("  'option' means another course can satisfy the same requirement.")
    print(f"  Run `check --want \"{code}\"` for the exact rule, including grades.")
    print()
    print(wrap(DISCLAIMER))
    return 0


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(
        prog="ubc-advisor",
        description="Check UBC course prerequisites against your transcript.",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    def shared(p):
        p.add_argument("--have", help="completed courses: 'CPSC 110,MATH 226:74'")
        p.add_argument("--year", type=int, choices=[1, 2, 3, 4, 5],
                       help="your year standing")
        p.add_argument("--program", help="e.g. 'Computer Science'")

    c = sub.add_parser("check", help="check one course")
    shared(c)
    c.add_argument("--want", required=True, help="course to check, e.g. 'CPSC 221'")
    c.set_defaults(func=cmd_check)

    s = sub.add_parser("sweep", help="list what you're eligible for")
    shared(s)
    s.add_argument("--subject", help="limit to one subject, e.g. CPSC")
    s.add_argument("--level", type=int, help="minimum course level, e.g. 300")
    s.add_argument("--all", action="store_true", help="include ineligible courses")
    s.add_argument("--graduate", action="store_true", help="include 500-level graduate courses")
    s.set_defaults(func=cmd_sweep)

    u = sub.add_parser("unlocks", help="what a course leads to")
    shared(u)
    u.add_argument("course", help="e.g. 'CPSC 221'")
    u.add_argument("--all", action="store_true", help="include courses still blocked")
    u.set_defaults(func=cmd_unlocks)

    p = sub.add_parser("path", help="what lies between you and a course")
    shared(p)
    p.add_argument("--want", required=True, help="target course, e.g. 'CPSC 404'")
    p.set_defaults(func=cmd_path)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
