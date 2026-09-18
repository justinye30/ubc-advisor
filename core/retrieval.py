"""Search policy_chunks.

Two modes:
  vector  — cosine similarity between the query and chunk embeddings.
  hybrid  — vector, fused with an exact-match leg for course codes.

The exact-match leg exists because embeddings are weak at literal tokens:
"STAT 251" and "STAT 200" look nearly identical to a vector model. It only
runs when the question contains a course code, so plain-English questions
get pure vector results either way.

Run:  python -m core.retrieval "can I retake a course I passed?" [--mode hybrid] [-k 5]
"""

import argparse
import re
import sys
from dataclasses import dataclass

from core.codes import IN_SCOPE_SUBJECTS
from core.db import connection
from core.embeddings import MODEL, embed_query, vector_literal

POOL = 20      # candidates per leg before fusion
RRF_K = 60     # standard reciprocal-rank-fusion constant

# 'STAT 251', 'stat251', 'CPSC_V 310', 'MATH 100A'
CODE_RE = re.compile(r"\b([A-Za-z]{2,5})(?:_[VvOo])?\s*(\d{3}[A-Za-z]?)\b")


@dataclass
class Hit:
    id: int
    source_url: str
    section_path: str
    content: str
    score: float


connect = connection   # pooled; use as `with connect() as conn:`


# ------------------------------------------------------------------ pure helpers

def code_tsquery(query: str, subjects: set[str]) -> str | None:
    """'Can STAT 251 replace MATH 200?' -> '(stat & 251) | (math & 200)'.

    Only known subjects count, so 'take 300-level courses' doesn't become
    a search for the word 'take'. Postgres tokenizes 'STAT_V 251' as
    'stat', 'v', '251', so shorthand like 'CPSC_V 310, 313' still matches
    a query for CPSC 313.
    """
    terms: list[str] = []
    for subject, number in CODE_RE.findall(query):
        if subject.upper() not in subjects:
            continue
        term = f"({subject.lower()} & {number.lower()})"
        if term not in terms:
            terms.append(term)
    return " | ".join(terms) or None


def rrf(rankings: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal rank fusion: score(id) = sum over lists of 1 / (k + rank)."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


# ------------------------------------------------------------------ queries

_subjects_cache: set[str] | None = None


def corpus_subjects(conn) -> set[str]:
    """Subject codes that actually appear in the policy text, plus our own."""
    global _subjects_cache
    if _subjects_cache is None:
        rows = conn.execute(
            r"SELECT DISTINCT (regexp_matches(content, '\m([A-Z]{2,5})_[VO]\M', 'g'))[1] AS s "
            "FROM policy_chunks"
        ).fetchall()
        _subjects_cache = {r["s"] for r in rows} | set(IN_SCOPE_SUBJECTS)
    return _subjects_cache


def vector_ranking(conn, qvec: list[float], limit: int) -> list[dict]:
    return conn.execute(
        """
        SELECT id, source_url, section_path, content,
               1 - (embedding <=> %(v)s::vector) AS score
        FROM policy_chunks
        WHERE embedding IS NOT NULL AND embedding_model = %(model)s
        ORDER BY embedding <=> %(v)s::vector
        LIMIT %(limit)s
        """,
        {"v": vector_literal(qvec), "model": MODEL, "limit": limit},
    ).fetchall()


def lexical_ranking(conn, tsquery: str, limit: int) -> list[dict]:
    # Computed inline: at ~100 rows a stored tsvector + GIN index buys nothing.
    return conn.execute(
        """
        SELECT id, source_url, section_path, content,
               ts_rank_cd(to_tsvector('english', content), q) AS score
        FROM policy_chunks, to_tsquery('english', %(q)s) AS q
        WHERE to_tsvector('english', content) @@ q
        ORDER BY score DESC, id
        LIMIT %(limit)s
        """,
        {"q": tsquery, "limit": limit},
    ).fetchall()


def search_policy(query: str, k: int = 5, mode: str = "hybrid",
                  conn=None, qvec: list[float] | None = None) -> list[Hit]:
    """Top-k chunks for a question. Pass qvec to reuse an existing query embedding."""
    if mode not in ("vector", "hybrid"):
        raise ValueError(f"unknown mode: {mode}")

    # Embed BEFORE borrowing a connection. The embedding call is a network
    # round trip that can take seconds (or wait out a rate limit); holding a
    # pooled connection idle through it starves other requests.
    qvec = qvec or embed_query(query)
    if conn is not None:
        return _search(conn, query, qvec, k, mode)
    with connect() as pooled:
        return _search(pooled, query, qvec, k, mode)


def _search(conn, query: str, qvec: list[float], k: int, mode: str) -> list[Hit]:
    vec_rows = vector_ranking(conn, qvec, POOL if mode == "hybrid" else k)

    tsq = code_tsquery(query, corpus_subjects(conn)) if mode == "hybrid" else None
    lex_rows = lexical_ranking(conn, tsq, POOL) if tsq else []

    if not lex_rows:
        return [Hit(r["id"], r["source_url"], r["section_path"], r["content"], r["score"])
                for r in vec_rows[:k]]

    by_id = {r["id"]: r for r in [*vec_rows, *lex_rows]}
    fused = rrf([[r["id"] for r in vec_rows], [r["id"] for r in lex_rows]])
    return [Hit(cid, by_id[cid]["source_url"], by_id[cid]["section_path"],
                by_id[cid]["content"], score)
            for cid, score in fused[:k]]


def main() -> int:
    ap = argparse.ArgumentParser(description="Search the policy corpus.")
    ap.add_argument("query")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--mode", choices=["vector", "hybrid"], default="hybrid")
    args = ap.parse_args()

    for i, hit in enumerate(search_policy(args.query, args.k, args.mode), start=1):
        body = hit.content.split("\n\n", 1)[-1].replace("\n", " ")
        print(f"\n{i}. [{hit.score:.4f}] {hit.section_path}")
        print(f"   {body[:160]}{'…' if len(body) > 160 else ''}")
        print(f"   {hit.source_url}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
