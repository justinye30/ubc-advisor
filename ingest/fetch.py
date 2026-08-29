"""Fetch UBC calendar subject index pages into raw_pages.

Politeness:
  - robots.txt parsed at runtime; can_fetch() checked before every request
  - Crawl-delay read from robots.txt (currently 10s), not hardcoded
  - Identifying User-Agent with contact email
  - Single-threaded, sequential

Run:  python -m ingest.fetch
"""

import hashlib
import logging
import os
import sys
import time
from urllib.robotparser import RobotFileParser

import psycopg
import requests
from dotenv import load_dotenv

from core.codes import CALENDAR_BASE, IN_SCOPE_SUBJECTS, subject_index_url

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fetch")

DATABASE_URL = os.environ["DATABASE_URL"]
USER_AGENT = os.environ["USER_AGENT"]
CALENDAR_YEAR = os.environ["CALENDAR_YEAR"]
ROBOTS_URL = f"{CALENDAR_BASE}/robots.txt"
DEFAULT_DELAY = 10.0
TIMEOUT = 30


def load_robots() -> tuple[RobotFileParser, float]:
    """Fetch and parse robots.txt. Returns (parser, crawl_delay_seconds)."""
    rp = RobotFileParser()
    rp.set_url(ROBOTS_URL)
    rp.read()
    delay = rp.crawl_delay(USER_AGENT) or rp.crawl_delay("*") or DEFAULT_DELAY
    log.info("robots.txt loaded, crawl-delay=%ss", delay)
    return rp, float(delay)


def fetch(url: str, session: requests.Session) -> tuple[str, str]:
    """GET a page. Returns (html, sha256)."""
    resp = session.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    html = resp.text
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
    return html, digest


def upsert_page(conn, url: str, page_type: str, html: str, digest: str) -> str:
    """Store a page. Returns 'inserted', 'updated', or 'unchanged'."""
    with conn.cursor() as cur:
        cur.execute("SELECT content_sha256 FROM raw_pages WHERE url = %s", (url,))
        row = cur.fetchone()

        if row and row[0] == digest:
            cur.execute(
                "UPDATE raw_pages SET fetched_at = now() WHERE url = %s", (url,)
            )
            return "unchanged"

        cur.execute(
            """
            INSERT INTO raw_pages
                (url, page_type, content_sha256, html, calendar_year)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (url) DO UPDATE SET
                content_sha256 = EXCLUDED.content_sha256,
                html           = EXCLUDED.html,
                fetched_at     = now(),
                calendar_year  = EXCLUDED.calendar_year
            """,
            (url, page_type, digest, html, CALENDAR_YEAR),
        )
        return "updated" if row else "inserted"


def main() -> int:
    rp, delay = load_robots()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    targets = [(s, subject_index_url(s)) for s in sorted(IN_SCOPE_SUBJECTS)]
    log.info("fetching %d subject index pages", len(targets))

    counts = {"inserted": 0, "updated": 0, "unchanged": 0, "failed": 0}

    with psycopg.connect(DATABASE_URL) as conn:
        for i, (subject, url) in enumerate(targets):
            if not rp.can_fetch(USER_AGENT, url):
                log.warning("robots.txt disallows %s — skipping", url)
                counts["failed"] += 1
                continue

            started = time.monotonic()
            try:
                html, digest = fetch(url, session)
                result = upsert_page(conn, url, "subject_index", html, digest)
                conn.commit()
                counts[result] += 1
                log.info(
                    "%-5s %-10s %6d bytes  %s", subject, result, len(html), digest[:12]
                )
            except requests.RequestException as exc:
                conn.rollback()
                counts["failed"] += 1
                log.error("%-5s FAILED  %s", subject, exc)

            if i < len(targets) - 1:
                remaining = delay - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(remaining)

    log.info(
        "done — %(inserted)d new, %(updated)d changed, "
        "%(unchanged)d unchanged, %(failed)d failed",
        counts,
    )
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
