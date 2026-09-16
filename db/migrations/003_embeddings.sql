-- Step 10: embeddings for policy_chunks.
--
-- Runs automatically on a fresh volume (after 002). On an existing volume,
-- apply by hand — do NOT `make reset`, it would wipe the extracted trees:
--   docker compose exec -T db psql -U advisor -d advisor < db/migrations/003_embeddings.sql
--
-- Safe to re-run.

-- voyage-4 returns 1024 dims, not the 1536 guessed in 002. Resizing is free
-- while every embedding is NULL; once vectors exist, this fails loudly on any
-- row of the wrong size, which is the behaviour we want.
ALTER TABLE policy_chunks ALTER COLUMN embedding TYPE vector(1024);

-- Which model produced each vector. Query and document vectors must come from
-- compatible models; search refuses to mix them.
ALTER TABLE policy_chunks ADD COLUMN IF NOT EXISTS embedding_model TEXT;

-- Approximate nearest-neighbour index, cosine distance (the <=> operator).
-- At ~100 rows the planner will still choose an exact scan — that's fine, and
-- it means recall numbers measure the embeddings, not index approximation.
CREATE INDEX IF NOT EXISTS policy_chunks_embedding_hnsw
    ON policy_chunks USING hnsw (embedding vector_cosine_ops);
