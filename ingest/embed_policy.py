"""Embed policy_chunks that don't have a vector yet.

Commits after every batch, so an interrupted run resumes where it stopped.

Run:  python -m ingest.embed_policy              # only rows with no embedding
      python -m ingest.embed_policy --dry-run    # count, don't call the API
      python -m ingest.embed_policy --redo       # re-embed everything (model change)
"""

import argparse
import logging
import os
import sys

import psycopg
import requests
from dotenv import load_dotenv

from core.embeddings import (
    DIM,
    MODEL,
    EmbeddingError,
    batches,
    embed_documents,
    vector_literal,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("embed")


def scalar(conn, query: str, params=None):
    """First column of the first row. Raises instead of returning None."""
    row = conn.execute(query, params).fetchone()
    if row is None:
        raise RuntimeError(f"query returned no rows: {query}")
    return row[0]


def column_dim(conn) -> int:
    """For a vector(N) column, Postgres stores N as the type modifier."""
    return scalar(
        conn,
        "SELECT atttypmod FROM pg_attribute "
        "WHERE attrelid = 'policy_chunks'::regclass AND attname = 'embedding'",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="count chunks and tokens only")
    ap.add_argument("--redo", action="store_true", help="re-embed every chunk")
    args = ap.parse_args()

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        dim = column_dim(conn)
        if dim != DIM:
            log.error("policy_chunks.embedding is vector(%d) but EMBED_DIM=%d — "
                      "apply db/migrations/003_embeddings.sql first", dim, DIM)
            return 1

        others = conn.execute(
            "SELECT embedding_model, count(*) FROM policy_chunks "
            "WHERE embedding IS NOT NULL AND embedding_model IS DISTINCT FROM %s "
            "GROUP BY 1", (MODEL,),
        ).fetchall()
        if others and not args.redo:
            log.error("chunks already embedded with a different model %s — "
                      "rerun with --redo to replace them", others)
            return 1

        where = "TRUE" if args.redo else "embedding IS NULL"
        rows = conn.execute(
            f"SELECT id, content FROM policy_chunks WHERE {where} ORDER BY id"
        ).fetchall()
        if not rows:
            log.info("nothing to embed")
            return 0

        est = sum(len(c) // 4 for _, c in rows)
        log.info("%d chunks, ~%d tokens, model=%s dim=%d", len(rows), est, MODEL, DIM)
        if args.dry_run:
            return 0

        used_total = 0
        with requests.Session() as session:
            for start, end in batches([c for _, c in rows]):
                batch = rows[start:end]
                try:
                    vectors, used = embed_documents([c for _, c in batch], session)
                except EmbeddingError as exc:
                    log.error("batch %d–%d failed: %s", start, end - 1, exc)
                    return 1

                with conn.cursor() as cur:
                    cur.executemany(
                        "UPDATE policy_chunks SET embedding = %s::vector, "
                        "embedding_model = %s, embedded_at = now() WHERE id = %s",
                        [(vector_literal(v), MODEL, cid) for (cid, _), v in zip(batch, vectors, strict=True)],
                    )
                conn.commit()
                used_total += used
                log.info("embedded chunks %d–%d  (%d tokens)", start, end - 1, used)

        missing = scalar(conn, "SELECT count(*) FROM policy_chunks WHERE embedding IS NULL")

    log.info("done — %d tokens billed, %d chunks still without embeddings", used_total, missing)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
