"""Embedding client tests. No network: requests is replaced with a fake."""

import pytest

from core import embeddings
from core.embeddings import EmbeddingError, batches, vector_literal


class FakeResponse:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.bodies = []

    def post(self, url, json, timeout, headers):
        self.bodies.append(json)
        return self.responses.pop(0)


def ok(n, dim=embeddings.DIM):
    # returned out of order on purpose: the client must sort by index
    data = [{"index": i, "embedding": [float(i)] * dim} for i in reversed(range(n))]
    return FakeResponse(200, {"data": data, "usage": {"total_tokens": 7 * n}})


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
    monkeypatch.setattr(embeddings.time, "sleep", lambda s: None)


def test_batches_respect_text_count():
    assert list(batches(["a"] * 5, max_texts=2)) == [(0, 2), (2, 4), (4, 5)]


def test_batches_respect_token_budget():
    texts = ["x" * 400] * 4          # ~101 tokens each
    assert list(batches(texts, max_tokens=250)) == [(0, 2), (2, 4)]


def test_oversized_single_text_still_gets_its_own_batch():
    assert list(batches(["x" * 10_000, "y"], max_tokens=100)) == [(0, 1), (1, 2)]


def test_batches_empty():
    assert list(batches([])) == []


def test_vector_literal_format():
    assert vector_literal([0.5, -1, 2.25]) == "[0.5,-1.0,2.25]"


def test_documents_and_queries_use_different_input_types():
    s = FakeSession([ok(2), ok(1)])
    embeddings.embed_documents(["a", "b"], session=s)
    embeddings.embed_query("q", session=s)
    assert [b["input_type"] for b in s.bodies] == ["document", "query"]


def test_vectors_come_back_in_input_order():
    vectors, tokens = embeddings.embed_documents(["a", "b", "c"], session=FakeSession([ok(3)]))
    assert [v[0] for v in vectors] == [0.0, 1.0, 2.0]
    assert tokens == 21


def test_retries_rate_limit_then_succeeds():
    s = FakeSession([FakeResponse(429, headers={"Retry-After": "2"}), FakeResponse(503), ok(1)])
    vectors, _ = embeddings.embed_documents(["a"], session=s)
    assert len(vectors) == 1 and len(s.bodies) == 3


def test_client_error_is_not_retried():
    s = FakeSession([FakeResponse(400, {"detail": "bad"})])
    with pytest.raises(EmbeddingError, match="400"):
        embeddings.embed_documents(["a"], session=s)
    assert len(s.bodies) == 1


def test_wrong_dimension_is_rejected():
    with pytest.raises(EmbeddingError, match="dim"):
        embeddings.embed_documents(["a"], session=FakeSession([ok(1, dim=8)]))


def test_missing_key_fails_before_any_request(monkeypatch):
    monkeypatch.delenv("VOYAGE_API_KEY")
    s = FakeSession([])
    with pytest.raises(EmbeddingError, match="VOYAGE_API_KEY"):
        embeddings.embed_query("q", session=s)
    assert s.bodies == []



def test_embed_queries_is_one_request():
    s = FakeSession([ok(3)])
    vectors = embeddings.embed_queries(["a", "b", "c"], session=s)
    assert len(vectors) == 3 and len(s.bodies) == 1
    assert s.bodies[0]["input_type"] == "query"


def test_throttle_spaces_requests(monkeypatch):
    clock = [1000.0]
    sleeps = []
    monkeypatch.setattr(embeddings.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(embeddings.time, "sleep", lambda s: (sleeps.append(s), clock.__setitem__(0, clock[0] + s)))
    monkeypatch.setattr(embeddings, "RPM_LIMIT", 3)
    monkeypatch.setattr(embeddings, "TPM_LIMIT", 0)
    monkeypatch.setattr(embeddings, "_last_sent", 0.0)

    s = FakeSession([ok(1), ok(1)])
    embeddings.embed_documents(["a"], session=s)
    embeddings.embed_documents(["b"], session=s)
    assert sleeps == [20.0]          # 3 RPM -> one request every 20s


def test_throttle_scales_with_tokens(monkeypatch):
    clock = [1000.0]
    sleeps = []
    monkeypatch.setattr(embeddings.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(embeddings.time, "sleep", lambda s: (sleeps.append(s), clock.__setitem__(0, clock[0] + s)))
    monkeypatch.setattr(embeddings, "RPM_LIMIT", 0)
    monkeypatch.setattr(embeddings, "TPM_LIMIT", 6000)
    monkeypatch.setattr(embeddings, "_last_sent", 0.0)

    s = FakeSession([ok(1), ok(1)])   # ok() reports 7 tokens used per text
    embeddings.embed_documents(["a"], session=s)
    embeddings.embed_documents(["b"], session=s)
    assert sleeps == [pytest.approx(60 * 7 / 6000)]


def test_request_larger_than_tpm_fails_immediately(monkeypatch):
    monkeypatch.setattr(embeddings, "TPM_LIMIT", 100)
    s = FakeSession([])
    with pytest.raises(EmbeddingError, match="never fit"):
        embeddings.embed_documents(["x" * 4000], session=s)
    assert s.bodies == []