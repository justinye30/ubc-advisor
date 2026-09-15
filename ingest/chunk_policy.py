"""Chunk cached policy pages into policy_chunks.

Reads raw_pages (page_type='policy'). Splits on heading boundaries and
never inside a paragraph, list, or table. Each chunk records the heading
path it sits under, so a citation can point at a section, not just a page.

No network, no LLM. Safe to re-run: each page's chunks are replaced in one
transaction. That also clears their embeddings, which is intended — if the
text changed, the old vectors are wrong.

Run:  python -m ingest.chunk_policy
"""

import logging
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass

import psycopg
from bs4 import BeautifulSoup
from bs4.element import Comment, NavigableString, Tag
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("chunk")

# Packing. Token counts are estimates (chars/4) until Step 10 picks a model.
TARGET_TOKENS = 350       # start a new chunk once adding a block would pass this
MAX_TOKENS = 800          # anything larger is logged; tables are never split
OVERLAP_MAX_TOKENS = 120  # carry the previous block forward only if it's this small

# Tried in order, first match wins. Confirm against a cached page (Part 3).
CONTENT_SELECTORS = [
    "article.node--view-mode-full",
    "main article",
    "main",
]

# If any of these survive into a chunk, the content root or chrome filter is wrong.
CHROME_CANARIES = ("Main navigation", "Print-friendly version", "Skip to main content")

SKIP_TAGS = ["nav", "script", "style", "form", "button", "noscript", "aside", "header", "footer"]
HEADINGS = {"h2": 2, "h3": 3, "h4": 4, "h5": 5}

SCOPE_PREFIXES = [
    ("/faculty-science/bachelor-science/", "B.Sc."),
    ("/faculty-science/bachelor-computer-science", "B.C.S."),
    ("/campus-wide-policies-and-regulations/", "Campus-wide"),
]


@dataclass
class Block:
    path: tuple[str, ...]   # headings above this block, outermost first
    text: str
    kind: str               # p | list | table


@dataclass
class Chunk:
    section_path: str
    content: str
    token_count: int


# ------------------------------------------------------------------ text

def clean(text: str) -> str:
    """Collapse whitespace, including the non-breaking spaces Drupal emits."""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def scope_for(url: str) -> str:
    for prefix, label in SCOPE_PREFIXES:
        if prefix in url:
            return label
    return "Calendar"


def mark_footnotes(root: Tag) -> None:
    """'CPSC_V 210<sup>1</sup>' would flatten to 'CPSC_V 2101' — a different
    course. Rewrite superscripts as ' [1]' before any text is extracted."""
    for sup in root.find_all("sup"):
        marker = clean(sup.get_text())
        sup.replace_with(f" [{marker}]" if marker else "")


def strip_share_widgets(root: Tag) -> None:
    """Remove the print/share widget wherever it sits in the content area.

    Removed by locating the mailto link directly and climbing to its
    smallest enclosing container, rather than testing whole subtrees during
    traversal — a whole-subtree test wrongly flags any ancestor that also
    happens to wrap the real content (as on pages with a single top-level
    wrapper div), silently discarding every paragraph beneath it.
    """
    for link in root.find_all("a", href=re.compile(r"^mailto:")):
        widget = link
        parent = widget.parent
        while (parent is not None and parent is not root
               and len(clean(parent.get_text(" "))) < 100):
            widget = parent
            parent = parent.parent
        widget.decompose()


def table_text(table: Tag) -> str:
    """One line per row, cells joined by ' | '. Footnote rows stay attached."""
    lines = []
    for tr in table.find_all("tr"):
        cells = [clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
        cells = [c for c in cells if c]
        if cells:
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def list_text(lst: Tag) -> str:
    items = [clean(li.get_text(" ")) for li in lst.find_all("li")]
    return "\n".join(f"- {i}" for i in items if i)


# ------------------------------------------------------------------ structure

def extract_blocks(root: Tag) -> list[Block]:
    """Walk the content root in document order, tracking the heading stack."""
    stack: list[tuple[int, str]] = []
    blocks: list[Block] = []

    def path() -> tuple[str, ...]:
        return tuple(h for _, h in stack)

    def add(text: str, kind: str) -> None:
        if text:
            blocks.append(Block(path(), text, kind))

    def visit(node: Tag) -> None:
        for child in node.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                add(clean(str(child)), "p")   # bare text directly inside a div
                continue
            if not isinstance(child, Tag) or child.name == "h1":
                continue

            name = child.name
            if name in HEADINGS:
                level = HEADINGS[name]
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, clean(child.get_text(" "))))
            elif name == "table":
                add(table_text(child), "table")
            elif name in ("ul", "ol"):
                add(list_text(child), "list")
            elif name in ("p", "blockquote", "dl"):
                add(clean(child.get_text(" ")), "p")
            else:
                visit(child)   # div, section, span wrappers — descend

    visit(root)
    return blocks


def group_by_section(blocks: list[Block]) -> list[list[Block]]:
    """Consecutive blocks under the same heading path form one section."""
    sections: list[list[Block]] = []
    for b in blocks:
        if sections and sections[-1][0].path == b.path:
            sections[-1].append(b)
        else:
            sections.append([b])
    return sections


def pack(section: list[Block]) -> list[list[Block]]:
    """Split a section into chunks at block boundaries.

    The last block of a chunk is repeated at the start of the next one if it's
    small and not a table — so a rule and the sentence qualifying it are never
    only seen apart.
    """
    groups: list[list[Block]] = []
    cur: list[Block] = []
    cur_tokens = 0

    for b in section:
        t = est_tokens(b.text)
        if cur and cur_tokens + t > TARGET_TOKENS:
            groups.append(cur)
            last = cur[-1]
            carry = [last] if last.kind != "table" and est_tokens(last.text) <= OVERLAP_MAX_TOKENS else []
            cur = carry
            cur_tokens = sum(est_tokens(x.text) for x in carry)
        cur.append(b)
        cur_tokens += t

    if cur:
        groups.append(cur)
    return groups


def chunk_page(url: str, html: str, stats: Counter) -> list[Chunk]:
    """Pure function: HTML in, chunks out. No DB — this is what the tests hit."""
    soup = BeautifulSoup(html, "lxml")

    h1 = soup.find("h1")
    doc_title = clean(h1.get_text(" ")) if h1 else url.rsplit("/", 1)[-1]

    root = None
    for sel in CONTENT_SELECTORS:
        root = soup.select_one(sel)
        if root is not None:
            stats[f"root:{sel}"] += 1
            break
    if root is None:
        stats["no_content_root"] += 1
        log.error("no content root found in %s", url)
        return []

    for tag in root.find_all(SKIP_TAGS):
        tag.decompose()
    strip_share_widgets(root)
    mark_footnotes(root)

    scope = scope_for(url)
    chunks: list[Chunk] = []

    for section in group_by_section(extract_blocks(root)):
        section_path = " > ".join([scope, doc_title, *section[0].path])
        for group in pack(section):
            body = "\n\n".join(b.text for b in group)
            # The path is part of the embedded text: a table row like
            # "CPSC_V 310, 313, 320 | 10" means nothing without it.
            content = f"{section_path}\n\n{body}"
            tokens = est_tokens(content)

            if tokens > MAX_TOKENS:
                stats["oversize_chunks"] += 1
                log.warning("oversize chunk (%d tokens): %s", tokens, section_path)
            if any(c in content for c in CHROME_CANARIES):
                stats["chrome_leaks"] += 1
                log.warning("page chrome leaked into chunk: %s", section_path)

            chunks.append(Chunk(section_path, content, tokens))

    return chunks


# ------------------------------------------------------------------ main

def write_chunks(conn, url: str, doc_title: str, chunks: list[Chunk], year: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM policy_chunks WHERE source_url = %s", (url,))
        cur.executemany(
            """
            INSERT INTO policy_chunks
                (source_url, doc_title, section_path, chunk_index,
                 content, token_count, calendar_year)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [(url, doc_title, c.section_path, i, c.content, c.token_count, year)
             for i, c in enumerate(chunks)],
        )


def main() -> int:
    database_url = os.environ["DATABASE_URL"]
    year = os.environ["CALENDAR_YEAR"]
    stats: Counter = Counter()

    with psycopg.connect(database_url) as conn:
        pages = conn.execute(
            "SELECT url, html FROM raw_pages WHERE page_type = 'policy' ORDER BY url"
        ).fetchall()
        if not pages:
            log.error("no policy pages cached — run `make fetch-policy` first")
            return 1

        total = 0
        for url, html in pages:
            chunks = chunk_page(url, html, stats)
            slug = url.rsplit("/", 1)[-1]
            if not chunks:
                stats["empty_pages"] += 1
                log.warning("%-45s produced no chunks — not writing", slug)
                continue

            doc_title = chunks[0].section_path.split(" > ")[1]
            try:
                write_chunks(conn, url, doc_title, chunks, year)
                conn.commit()
            except psycopg.Error:
                conn.rollback()
                raise

            tokens = [c.token_count for c in chunks]
            total += len(chunks)
            log.info("%-45s %3d chunks  median %4d  max %4d",
                     slug[:45], len(chunks), sorted(tokens)[len(tokens) // 2], max(tokens))

    log.info("done — %d chunks from %d pages", total, len(pages))
    for key, n in sorted(stats.items()):
        log.info("  %-32s %d", key, n)

    problems = stats["empty_pages"] + stats["chrome_leaks"] + stats["no_content_root"]
    if problems:
        log.error("%d problem(s) — inspect before embedding anything", problems)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
