-- Enable pgvector. Required before any vector-typed column can be declared.
CREATE EXTENSION IF NOT EXISTS vector;

-- Smoke test only. Replaced by the real schema in 002.
CREATE TABLE IF NOT EXISTS _scaffold_check (
    id          SERIAL PRIMARY KEY,
    note        TEXT,
    probe       vector(3),
    created_at  TIMESTAMPTZ DEFAULT now()
);

INSERT INTO _scaffold_check (note, probe)
VALUES ('scaffold ok', '[1,2,3]');
