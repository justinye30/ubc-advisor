"""Text embeddings via Voyage AI.

Anthropic doesn't offer an embedding model; its docs point to Voyage.
Called over plain HTTPS with `requests` (already a dependency) rather than
the voyageai SDK — one less package to keep working on Python 3.14.

Documents and queries are embedded differently (Voyage's `input_type`),
so they have separate entry points. Mixing them up silently lowers recall.
"""

import logging
import os
import time

import requests

log = logging.getLogger("embeddings")

API_URL = "https://api.voyageai.com/v1/embeddings"
MODEL = os.environ.get("EMBED_MODEL", "voyage-4")
DIM = int(os.environ.get("EMBED_DIM", "1024"))

# Client-side throttle. 0 = off (fine once a payment method is on file).
# Free trial without a payment method is 3 RPM / 10K TPM: set EMBED_RPM=3
# and EMBED_TPM a little under 10000, since our token counts are estimates.
RPM_LIMIT = int(os.environ.get("EMBED_RPM", "0"))
TPM_LIMIT = int(os.environ.get("EMBED_TPM", "0"))

MAX_BATCH_TEXTS = 128
# Estimated (chars/4); API cap for voyage-4 is 320K. Under a TPM limit a
# single request must fit well inside one minute's budget, or it can never
# succeed no matter how long we wait.
MAX_BATCH_TOKENS = min(60_000, TPM_LIMIT // 2) if TPM_LIMIT else 60_000
TIMEOUT = 60
MAX_RETRIES = 6

_last_sent = 0.0     # monotonic time of the previous request
_last_tokens = 0     # tokens in the previous request


class EmbeddingError(RuntimeError):
    pass


def batches(texts: list[str], max_texts: int = MAX_BATCH_TEXTS,
            max_tokens: int = MAX_BATCH_TOKENS):
    """Yield (start, end) slices that respect both per-request limits."""
    start, tokens = 0, 0
    for i, text in enumerate(texts):
        n = len(text) // 4 + 1
        if i > start and (i - start >= max_texts or tokens + n > max_tokens):
            yield start, i
            start, tokens = i, 0
        tokens += n
    if start < len(texts):
        yield start, len(texts)


def vector_literal(vec: list[float]) -> str:
    """pgvector's text format: '[0.1,0.2,...]'. Cast with ::vector in SQL."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _estimate_tokens(texts: list[str]) -> int:
    return sum(len(t) // 4 + 1 for t in texts)


def _throttle() -> None:
    """Space requests so we stay under RPM_LIMIT and TPM_LIMIT on average."""
    gap = 0.0
    if RPM_LIMIT:
        gap = max(gap, 60 / RPM_LIMIT)
    if TPM_LIMIT:
        gap = max(gap, 60 * _last_tokens / TPM_LIMIT)
    wait = _last_sent + gap - time.monotonic()
    if wait > 0:
        log.info("throttling %.0fs to stay under rate limits", wait)
        time.sleep(wait)


def _record(tokens: int) -> None:
    global _last_sent, _last_tokens
    _last_sent, _last_tokens = time.monotonic(), tokens


def _retry_after(resp: requests.Response, attempt: int) -> float:
    try:
        return max(1.0, float(resp.headers.get("Retry-After", "")))
    except ValueError:
        return float(min(60, 2 ** attempt))


def _embed(texts: list[str], input_type: str, session=None) -> tuple[list[list[float]], int]:
    key = os.environ.get("VOYAGE_API_KEY")
    if not key:
        raise EmbeddingError("VOYAGE_API_KEY is not set — add it to .env and recreate the container")

    body = {
        "input": texts,
        "model": MODEL,
        "input_type": input_type,
        "output_dimension": DIM,
        "truncation": False,   # error on over-long input rather than silently cut it
    }
    http = session or requests
    est = _estimate_tokens(texts)
    if TPM_LIMIT and est > TPM_LIMIT:
        raise EmbeddingError(f"request of ~{est} tokens can never fit EMBED_TPM={TPM_LIMIT}")

    for attempt in range(MAX_RETRIES):
        _throttle()
        resp = http.post(API_URL, json=body, timeout=TIMEOUT,
                         headers={"Authorization": f"Bearer {key}"})
        _record(est)

        if resp.status_code == 429 or resp.status_code >= 500:
            wait = _retry_after(resp, attempt)
            log.warning("voyage %s — retrying in %.0fs: %s",
                        resp.status_code, wait, resp.text[:200])
            time.sleep(wait)
            continue
        if resp.status_code != 200:
            raise EmbeddingError(f"voyage {resp.status_code}: {resp.text[:300]}")

        payload = resp.json()
        rows = sorted(payload["data"], key=lambda d: d["index"])
        vectors = [r["embedding"] for r in rows]

        if len(vectors) != len(texts):
            raise EmbeddingError(f"sent {len(texts)} texts, got {len(vectors)} vectors")
        if any(len(v) != DIM for v in vectors):
            raise EmbeddingError(f"expected {DIM}-dim vectors from {MODEL}")

        used = payload.get("usage", {}).get("total_tokens", 0)
        _record(used or est)   # real count, when the API reports one
        return vectors, used

    raise EmbeddingError(f"gave up after {MAX_RETRIES} attempts")


def embed_documents(texts: list[str], session=None) -> tuple[list[list[float]], int]:
    """One request. Returns (vectors, tokens_used). Use batches() for long lists."""
    return _embed(texts, "document", session)


def embed_query(text: str, session=None) -> list[float]:
    vectors, _ = _embed([text], "query", session)
    return vectors[0]


def embed_queries(texts: list[str], session=None) -> list[list[float]]:
    """Several queries in one request — the eval uses this to stay at 1 RPM."""
    vectors, _ = _embed(texts, "query", session)
    return vectors
