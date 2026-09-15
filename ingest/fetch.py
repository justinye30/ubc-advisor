"""Fetch UBC calendar pages into raw_pages.

  python -m ingest.fetch                  # subject index pages (Week 1)
  python -m ingest.fetch --type policy    # policy pages (Week 2)

Politeness:
  - robots.txt parsed at runtime; can_fetch() checked before every request
  - Crawl-delay read from robots.txt (currently 10s), not hardcoded
  - Identifying User-Agent with contact email
  - Single-threaded, sequential
"""

import argparse
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
from ingest.policy_pages import POLICY_PAGES

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


def build_targets(page_type: str) -> list[tuple[str, str]]:
    """Returns [(label, url), ...] for a page type."""
    if page_type == "subject_index":
        return [(s, subject_index_url(s)) for s in sorted(IN_SCOPE_SUBJECTS)]
    if page_type == "policy":
        return [(u.rstrip("/").rsplit("/", 1)[-1], u) for u in POLICY_PAGES]
    raise ValueError(f"unknown page type: {page_type}")


def fetch(url: str, session: requests.Session) -> tuple[str, str, str]:
    """GET a page. Returns (final_url, html, sha256).

    final_url differs from url only if the server redirected. We store under
    the final URL so citations point where a browser would actually land.
    """
    resp = session.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    html = resp.text
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
    return resp.url, html, digest


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
                page_type      = EXCLUDED.page_type,
                content_sha256 = EXCLUDED.content_sha256,
                html           = EXCLUDED.html,
                fetched_at     = now(),
                calendar_year  = EXCLUDED.calendar_year
            """,
            (url, page_type, digest, html, CALENDAR_YEAR),
        )
        return "updated" if row else "inserted"


def crawl(page_type: str) -> int:
    rp, delay = load_robots()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    targets = build_targets(page_type)
    log.info("fetching %d %s pages (~%ds)", len(targets), page_type,
             int(delay * (len(targets) - 1)))

    counts = {"inserted": 0, "updated": 0, "unchanged": 0, "failed": 0}

    with psycopg.connect(DATABASE_URL) as conn:
        for i, (label, url) in enumerate(targets):
            if not rp.can_fetch(USER_AGENT, url):
                log.warning("robots.txt disallows %s — skipping", url)
                counts["failed"] += 1
                continue

            started = time.monotonic()
            try:
                final_url, html, digest = fetch(url, session)
                if final_url != url:
                    log.warning("%s redirected to %s — update policy_pages.py",
                                url, final_url)
                result = upsert_page(conn, final_url, page_type, html, digest)
                conn.commit()
                counts[result] += 1
                log.info("%-45s %-10s %7d bytes  %s",
                         label[:45], result, len(html), digest[:12])
            except requests.RequestException as exc:
                conn.rollback()
                counts["failed"] += 1
                log.error("%-45s FAILED  %s", label[:45], exc)

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


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch calendar pages into raw_pages.")
    ap.add_argument("--type", dest="page_type", default="subject_index",
                    choices=["subject_index", "policy"])
    args = ap.parse_args()
    return crawl(args.page_type)


if __name__ == "__main__":
    sys.exit(main())
