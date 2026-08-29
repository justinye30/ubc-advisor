"""Parse cached subject index pages into courses rows.

Reads raw_pages (page_type='subject_index'), extracts one row per course.
Prerequisite and corequisite text is stored VERBATIM — parsing its meaning
is Step 5's job.

No network access. Safe to re-run.

Run:  python -m ingest.parse_courses
"""

import logging
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass

import psycopg
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from core.codes import OutOfScope, course_url, is_in_scope, normalize

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("parse")

DATABASE_URL = os.environ["DATABASE_URL"]
CALENDAR_YEAR = os.environ["CALENDAR_YEAR"]

# "CPSC_V 221 (4)" — code and credit value from the h3, title stripped first
HEADING_RE = re.compile(
    r"^\s*([A-Za-z]{2,5}(?:_[VO])?\s*\d{3}[A-Za-z]?)"   # code
    r"\s*\(\s*([\d.]+(?:\s*-\s*[\d.]+)?)\s*\)"          # credits, allows "3-6" ranges
    r"\s*(.*)$"                                         # title, whatever's left
)

# "[3-2-0]" or "[2.5-2-0]" or "[4-2-2*]" — separates description from requirements
HOURS_RE = re.compile(r"\[\s*[\d.]+\s*-\s*[\d.]+\s*-\s*[\d.]+\*?\s*\]")

# Requirement sentences. Non-greedy, stop at the next requirement keyword or end.
PREREQ_RE = re.compile(
    r"Prerequisite:\s*(.+?)(?=\s*(?:Corequisite:|Equivalency:|$))",
    re.IGNORECASE | re.DOTALL,
)
COREQ_RE = re.compile(
    r"Corequisite:\s*(.+?)(?=\s*(?:Prerequisite:|Equivalency:|$))",
    re.IGNORECASE | re.DOTALL,
)

# Grading-policy sentences that trail prerequisites but aren't requirements.
POLICY_TAIL_RE = re.compile(
    r"\s*(?:This course is not eligible for Credit/D/Fail grading|"
    r"Credit will (?:only be |be )?granted for only one of[^.]*)\.?\s*$",
    re.IGNORECASE,
)


@dataclass
class ParsedCourse:
    code: str
    subject: str
    number: str
    title: str | None
    credits: float | None
    description: str | None
    prereq_text: str | None
    coreq_text: str | None


def clean(text: str) -> str:
    """Collapse whitespace, including the non-breaking spaces Drupal emits."""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def split_requirements(body: str) -> tuple[str | None, str | None, str | None]:
    """Split a course paragraph into (description, prereq_text, coreq_text)."""
    hours = HOURS_RE.search(body)
    if hours:
        description = clean(body[: hours.start()])
        tail = body[hours.end() :]
    else:
        # No contact-hours marker. Fall back to splitting at the first keyword.
        keyword = re.search(r"(Prerequisite:|Corequisite:)", body, re.IGNORECASE)
        if keyword:
            description = clean(body[: keyword.start()])
            tail = body[keyword.start() :]
        else:
            return clean(body) or None, None, None

    prereq = PREREQ_RE.search(tail)
    coreq = COREQ_RE.search(tail)

    def strip_policy(s: str | None) -> str | None:
        """Remove trailing grading-policy sentences that aren't requirements."""
        if s is None:
            return None
        cleaned = POLICY_TAIL_RE.sub("", s).strip().rstrip(".")
        return cleaned or None

    return (
        description or None,
        strip_policy(clean(prereq.group(1))) if prereq else None,
        strip_policy(clean(coreq.group(1))) if coreq else None,
    )


def parse_article(article, stats: Counter) -> ParsedCourse | None:
    """Extract one course from an <article> element. Returns None on any skip."""
    h3 = article.find("h3")
    if h3 is None:
        stats["no_heading"] += 1
        return None

    # Some subjects wrap the title in <strong>, others don't. Prefer the
    # element when present; otherwise take whatever trails the credits.
    strong = h3.find("strong")
    strong_title = clean(strong.get_text()) if strong else None
    if strong:
        strong.extract()

    match = HEADING_RE.match(clean(h3.get_text()))
    if not match:
        stats["bad_heading"] += 1
        log.debug("unparseable heading: %r", clean(h3.get_text()))
        return None

    raw_code, credits_str, trailing = match.groups()
    title = strong_title or clean(trailing) or None

    try:
        code = normalize(raw_code)
    except OutOfScope:
        stats["okanagan"] += 1
        return None
    except ValueError:
        stats["bad_code"] += 1
        log.debug("bad code: %r", raw_code)
        return None

    if not is_in_scope(code):
        stats["out_of_scope_subject"] += 1
        return None

    paragraph = article.find("p")
    if paragraph is None:
        stats["no_paragraph"] += 1
        description = prereq = coreq = None
    else:
        # Strip the empty <em></em> the template always emits
        for em in paragraph.find_all("em"):
            if not clean(em.get_text()):
                em.extract()
        description, prereq, coreq = split_requirements(paragraph.get_text())
        if not HOURS_RE.search(paragraph.get_text()):
            stats["no_hours_marker"] += 1

    subject, number = code.split()
    stats["parsed"] += 1

    return ParsedCourse(
        code=code,
        subject=subject,
        number=number,
        title=title,
        credits = float(credits_str.split("-")[0]) if credits_str else None,
        description=description,
        prereq_text=prereq,
        coreq_text=coreq,
    )


def upsert_course(conn, c: ParsedCourse, source_url: str, fetched_at) -> None:
    """Insert or update. Never overwrites prereq_tree — that's Step 5's column."""
    status = "pending" if c.prereq_text or c.coreq_text else "no_prereq"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO courses (
                code, subject, number, title, credits, description,
                prereq_text, coreq_text, extraction_status,
                source_url, calendar_year, fetched_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (code) DO UPDATE SET
                title         = EXCLUDED.title,
                credits       = EXCLUDED.credits,
                description   = EXCLUDED.description,
                prereq_text   = EXCLUDED.prereq_text,
                coreq_text    = EXCLUDED.coreq_text,
                source_url    = EXCLUDED.source_url,
                calendar_year = EXCLUDED.calendar_year,
                fetched_at    = EXCLUDED.fetched_at,
                extraction_status = CASE
                    WHEN courses.prereq_text IS DISTINCT FROM EXCLUDED.prereq_text
                      OR courses.coreq_text  IS DISTINCT FROM EXCLUDED.coreq_text
                    THEN EXCLUDED.extraction_status
                    ELSE courses.extraction_status
                END,
                prereq_tree = CASE
                    WHEN courses.prereq_text IS DISTINCT FROM EXCLUDED.prereq_text
                    THEN NULL ELSE courses.prereq_tree
                END,
                coreq_tree = CASE
                    WHEN courses.coreq_text IS DISTINCT FROM EXCLUDED.coreq_text
                    THEN NULL ELSE courses.coreq_tree
                END
            """,
            (
                c.code, c.subject, c.number, c.title, c.credits, c.description,
                c.prereq_text, c.coreq_text, status,
                source_url, CALENDAR_YEAR, fetched_at,
            ),
        )


def main() -> int:
    stats: Counter = Counter()

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT url, html, fetched_at FROM raw_pages "
                "WHERE page_type = 'subject_index' ORDER BY url"
            )
            pages = cur.fetchall()

        if not pages:
            log.error("no subject_index pages in raw_pages — run ingest.fetch first")
            return 1

        for url, html, fetched_at in pages:
            soup = BeautifulSoup(html, "lxml")
            articles = soup.select("article.node--type-course")
            before = stats["parsed"]

            for article in articles:
                parsed = parse_article(article, stats)
                if parsed is None:
                    continue
                upsert_course(conn, parsed, course_url(parsed.code), fetched_at)

            conn.commit()
            log.info(
                "%-58s %3d articles -> %3d courses",
                url.rsplit("/", 1)[-1],
                len(articles),
                stats["parsed"] - before,
            )

    log.info("--- summary ---")
    for key in sorted(stats):
        log.info("%-24s %d", key, stats[key])

    anomalies = sum(
        stats[k] for k in ("no_heading", "bad_heading", "bad_code", "no_paragraph")
    )
    if anomalies:
        log.warning(
            "%d articles could not be parsed — inspect before trusting this run",
            anomalies,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
