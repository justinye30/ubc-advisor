"""Command-line interface for prerequisite checking.

  check  — can I take one course, and if not, what's missing
  sweep  — what am I eligible for

This is presentation only. All logic lives in core.evaluator.
"""

import argparse
import sys

from core.codes import OutOfScope, course_url, normalize
from core.evaluator import INDETERMINATE, NOT_SATISFIED, SATISFIED, evaluate
from core.repo import Course, get_course, list_courses, suggest_codes
from core.transcript import Transcript

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
            row(MARK[state], course, result.headline if show_reason else "")

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

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
