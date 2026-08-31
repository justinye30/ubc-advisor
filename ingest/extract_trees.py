"""Extract boolean requirement trees from verbatim prerequisite text.

Every tree is validated mechanically before being written:
  1. Conforms to the node schema (core.tree.validate)
  2. Every COURSE code with tracked=true exists in the courses table
  3. Every course code in the SOURCE TEXT appears somewhere in the tree

Check 3 catches dropped clauses, which spot-checking would never find.
Failures are written with status='flagged', never as truth.

Run:  python -m ingest.extract_trees [--limit N] [--code 'CPSC 320'] [--redo]
"""

import argparse
import json
import logging
import os
import re
import sys
from collections import Counter

import psycopg
from anthropic import Anthropic
from dotenv import load_dotenv

from core.codes import OutOfScope, is_in_scope, normalize, try_normalize
from core.tree import TreeError, course_codes, edges, has_indeterminate, validate, walk

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("extract")

DATABASE_URL = os.environ["DATABASE_URL"]
MODEL = "claude-sonnet-4-6"

# Any course-code-shaped token in prose, for the coverage check
CODE_IN_TEXT_RE = re.compile(r"\b([A-Z]{2,5})(_[VO])?\s+(\d{3}[A-Z]?)\b")

SYSTEM_PROMPT = """You convert UBC course prerequisite text into a JSON boolean tree.

ALLOWED OPS
  ALL_OF        {"op":"ALL_OF","children":[...]}          every child must hold
  ONE_OF        {"op":"ONE_OF","children":[...]}          at least one child
  COURSE        {"op":"COURSE","code":"CPSC 221","tracked":true}
  MIN_GRADE     {"op":"MIN_GRADE","percent":68,"child":{...}}
  MIN_CREDITS   {"op":"MIN_CREDITS","credits":3,
                 "from":{"subjects":["MATH","STAT"],"level_min":200}}
  STANDING      {"op":"STANDING","year":3}
  PROGRAM       {"op":"PROGRAM","name":"Computer Science"}
  PERMISSION    {"op":"PERMISSION","note":"permission of the department"}
  OUT_OF_SCOPE  {"op":"OUT_OF_SCOPE","code":"MATH_O 220","reason":"okanagan"}
  EXTERNAL_LIST {"op":"EXTERNAL_LIST","description":"...","url":"..."}
  UNPARSED      {"op":"UNPARSED","text":"the exact clause you could not map"}

RULES
1. Normalize codes: strip _V, single space. "CPSC_V 221" -> "CPSC 221".
2. Codes with _O are Okanagan: emit OUT_OF_SCOPE, never COURSE.
3. Preserve nesting exactly. Lettered groups "(a) ... (b) ..." under "All of"
   are ALL_OF children; each lettered group is usually a ONE_OF.
4. NEVER invent a course code that does not appear in the source text.
5. NEVER drop a clause. If a clause does not map cleanly to an op, wrap that
   clause verbatim in UNPARSED rather than approximating it.
6. A bare single requirement is still a valid tree: {"op":"COURSE",...}.
7. Output JSON only. No prose, no markdown fences.
8. "N credits from one of [explicit course list]" is a ONE_OF over those
   courses, not MIN_CREDITS. Use MIN_CREDITS only when the set is described
   by a pattern (subject and/or level) rather than enumerated.
9. Some requirements name programs rather than courses (e.g. "Arts One").
    Emit PROGRAM, not COURSE.
10. A bare course code, with or without square brackets (e.g. "CPSC 314" or
    "[CPSC320]"), is a single-course requirement:
    {"op":"COURSE","code":"CPSC 314","tracked":true}
11. A corequisite appearing as a branch inside a prerequisite (e.g. "or (d)
    SCIE_V 001 as a corequisite") cannot be verified from a transcript.
    Emit UNPARSED with the clause verbatim.
12. BC secondary school courses (PHYS 12, MATH 12, PREC 12, CALC 12, CHEM 11,
    etc.) are COURSE nodes with "tracked": false. Ignore trailing glossary
    sentences that expand these abbreviations.

EXAMPLES

Input: CPSC_V 213 and either CPSC_V 221 or DSCI_V 221
Output: {"op":"ALL_OF","children":[
  {"op":"COURSE","code":"CPSC 213","tracked":true},
  {"op":"ONE_OF","children":[
    {"op":"COURSE","code":"CPSC 221","tracked":true},
    {"op":"COURSE","code":"DSCI 221","tracked":true}]}]}

Input: One of CPSC_V 210, CPEN_V 221 and either (a) one of CPSC_V 121, MATH_V 220, MATH_O 220 or (b) a score of 68% or higher in MATH_V 226
Output: {"op":"ALL_OF","children":[
  {"op":"ONE_OF","children":[
    {"op":"COURSE","code":"CPSC 210","tracked":true},
    {"op":"COURSE","code":"CPEN 221","tracked":true}]},
  {"op":"ONE_OF","children":[
    {"op":"ONE_OF","children":[
      {"op":"COURSE","code":"CPSC 121","tracked":true},
      {"op":"COURSE","code":"MATH 220","tracked":true},
      {"op":"OUT_OF_SCOPE","code":"MATH_O 220","reason":"okanagan"}]},
    {"op":"MIN_GRADE","percent":68,
     "child":{"op":"COURSE","code":"MATH 226","tracked":true}}]}]}

Input: All of the following with a minimum grade of 76% in each of: (a) CPSC_V 310 or CPEN_V 321, (b) CPSC_V 313 or CPEN_V 331
Output: {"op":"ALL_OF","children":[
  {"op":"MIN_GRADE","percent":76,"child":{"op":"ONE_OF","children":[
    {"op":"COURSE","code":"CPSC 310","tracked":true},
    {"op":"COURSE","code":"CPEN 321","tracked":true}]}},
  {"op":"MIN_GRADE","percent":76,"child":{"op":"ONE_OF","children":[
    {"op":"COURSE","code":"CPSC 313","tracked":true},
    {"op":"COURSE","code":"CPEN 331","tracked":true}]}}]}

Input: CPSC 344 and one of STAT 200, PSYC 218, SOCI 328
Output: {"op":"ALL_OF","children":[
  {"op":"COURSE","code":"CPSC 344","tracked":true},
  {"op":"ONE_OF","children":[
    {"op":"COURSE","code":"STAT 200","tracked":true},
    {"op":"COURSE","code":"PSYC 218","tracked":false},
    {"op":"COURSE","code":"SOCI 328","tracked":false}]}]}

Input: Third-year standing in a Computer Science or Computer Engineering specialization, and permission of the department
Output: {"op":"ALL_OF","children":[
  {"op":"STANDING","year":3},
  {"op":"ONE_OF","children":[
    {"op":"PROGRAM","name":"Computer Science"},
    {"op":"PROGRAM","name":"Computer Engineering"}]},
  {"op":"PERMISSION","note":"permission of the department"}]}
"""


def extract(client: Anthropic, text: str) -> dict:
    resp = client.messages.create(
        model=MODEL, max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    raw = "".join(b.text for b in resp.content if b.type == "text").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    if not raw:
        raise json.JSONDecodeError("model returned empty text", "", 0)
    decoder = json.JSONDecoder()
    tree, _ = decoder.raw_decode(raw)
    return tree


def fix_tracked(node: dict) -> None:
    """tracked is derivable, not a judgment call. Overwrite whatever the model said."""
    for n in walk(node):
        if n["op"] == "COURSE":
            n["tracked"] = is_in_scope(n["code"])


def codes_in_text(text: str) -> set[str]:
    """Vancouver course codes mentioned in the source, normalized."""
    found = set()
    for subject, campus, number in CODE_IN_TEXT_RE.findall(text):
        code = try_normalize(f"{subject}{campus} {number}")
        if code:
            found.add(code)
    return found


def check_coverage(tree: dict, text: str) -> list[str]:
    """Codes present in the source text but missing from the tree."""
    in_tree = course_codes(tree)
    # OUT_OF_SCOPE nodes carry raw _O codes; collect their normalized subjects too
    missing = codes_in_text(text) - in_tree
    return sorted(missing)


def check_known(conn, tree: dict) -> list[str]:
    """Tracked COURSE codes that don't exist in the courses table."""
    tracked = course_codes(tree, include_untracked=False)
    if not tracked:
        return []
    with conn.cursor() as cur:
        cur.execute("SELECT code FROM courses WHERE code = ANY(%s)", (list(tracked),))
        known = {row[0] for row in cur.fetchall()}
    return sorted(tracked - known)


def write_tree(conn, code: str, tree: dict, status: str, notes: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE courses
               SET prereq_tree = %s, extraction_status = %s,
                   extraction_notes = %s, extracted_at = now()
               WHERE code = %s""",
            (json.dumps(tree), status, notes, code),
        )
        cur.execute(
            "DELETE FROM prereq_edges WHERE course_code = %s AND relation = 'prereq'",
            (code,),
        )
        for requires, optional in edges(tree):
            cur.execute(
                """INSERT INTO prereq_edges
                     (course_code, requires_code, relation, is_optional)
                   VALUES (%s, %s, 'prereq', %s)
                   ON CONFLICT DO NOTHING""",
                (code, requires, optional),
            )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--code", help="extract a single course")
    ap.add_argument("--redo", action="store_true", help="re-extract flagged/parsed too")
    ap.add_argument("--status", help="only extract courses with this extraction_status")
    args = ap.parse_args()

    client = Anthropic()
    stats: Counter = Counter()

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            if args.code:
                cur.execute(
                    "SELECT code, prereq_text FROM courses "
                    "WHERE prereq_text IS NOT NULL AND code = %s ORDER BY code",
                    (args.code,),
                )
            elif args.status:
                cur.execute(
                    "SELECT code, prereq_text FROM courses "
                    "WHERE prereq_text IS NOT NULL AND extraction_status = %s "
                    "ORDER BY code LIMIT %s",
                    (args.status, args.limit),
                )
            elif args.redo:
                cur.execute(
                    "SELECT code, prereq_text FROM courses "
                    "WHERE prereq_text IS NOT NULL ORDER BY code LIMIT %s",
                    (args.limit,),
                )
            else:
                cur.execute(
                    "SELECT code, prereq_text FROM courses "
                    "WHERE prereq_text IS NOT NULL "
                    "AND extraction_status = 'pending' ORDER BY code LIMIT %s",
                    (args.limit,),
                )
            rows = cur.fetchall()

        log.info("extracting %d courses with model %s", len(rows), MODEL)

        for code, text in rows:
            try:
                tree = extract(client, text)
                fix_tracked(tree)
                validate(tree)
            except (json.JSONDecodeError, TreeError) as exc:
                stats["invalid"] += 1
                log.warning("%-10s INVALID  %s", code, exc)
                log.warning("  input:  %r", text[:150])
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE courses SET extraction_status='flagged',
                           extraction_notes=%s, extracted_at=now() WHERE code=%s""",
                        (f"{type(exc).__name__}: {exc}", code),
                    )
                conn.commit()
                continue

            problems = []
            unknown = check_known(conn, tree)
            if unknown:
                problems.append(f"unknown codes: {', '.join(unknown)}")
            missing = check_coverage(tree, text)
            if missing:
                problems.append(f"codes in text but not tree: {', '.join(missing)}")
            if has_indeterminate(tree):
                problems.append("contains PERMISSION/EXTERNAL_LIST/UNPARSED")

            if unknown or missing:
                status, bucket = "flagged", "flagged"
            elif has_indeterminate(tree):
                status, bucket = "parsed", "parsed_with_indeterminate"
            else:
                status, bucket = "parsed", "parsed"

            stats[bucket] += 1
            write_tree(conn, code, tree, status, "; ".join(problems) or None)
            conn.commit()

            marker = "!" if status == "flagged" else " "
            log.info("%s %-10s %-8s %s", marker, code, status, "; ".join(problems))

    log.info("--- summary ---")
    for key in sorted(stats):
        log.info("%-28s %d", key, stats[key])
    return 0


if __name__ == "__main__":
    sys.exit(main())
