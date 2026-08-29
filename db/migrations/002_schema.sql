DROP TABLE IF EXISTS _scaffold_check;


CREATE TABLE raw_pages (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    url             TEXT        NOT NULL UNIQUE,
    page_type       TEXT        NOT NULL,
    content_sha256  TEXT        NOT NULL,
    html            TEXT        NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    calendar_year   TEXT        NOT NULL,
    CONSTRAINT raw_pages_page_type_check
        CHECK (page_type IN ('subject_index', 'course', 'program', 'policy'))
);

CREATE INDEX raw_pages_page_type_idx ON raw_pages (page_type);


CREATE TABLE courses (
    code                TEXT PRIMARY KEY,
    subject             TEXT        NOT NULL,
    number              TEXT        NOT NULL,
    title               TEXT,
    credits             NUMERIC(4,1),
    description         TEXT,

    prereq_text         TEXT,
    coreq_text          TEXT,

    prereq_tree         JSONB,
    coreq_tree          JSONB,

    extraction_status   TEXT        NOT NULL DEFAULT 'pending',
    extraction_notes    TEXT,
    extracted_at        TIMESTAMPTZ,

    source_url          TEXT        NOT NULL,
    calendar_year       TEXT        NOT NULL,
    fetched_at          TIMESTAMPTZ,

    CONSTRAINT courses_code_format_check
        CHECK (code ~ '^[A-Z]{2,5} [0-9]{3}[A-Z]?$'),
    CONSTRAINT courses_extraction_status_check
        CHECK (extraction_status IN
               ('pending', 'no_prereq', 'parsed', 'flagged', 'human_verified'))
);

CREATE INDEX courses_subject_idx           ON courses (subject);
CREATE INDEX courses_extraction_status_idx ON courses (extraction_status);
CREATE INDEX courses_prereq_tree_idx       ON courses USING gin (prereq_tree);


CREATE TABLE prereq_edges (
    course_code     TEXT NOT NULL REFERENCES courses(code) ON DELETE CASCADE,
    requires_code   TEXT NOT NULL,
    relation        TEXT NOT NULL,
    is_optional     BOOLEAN NOT NULL,
    PRIMARY KEY (course_code, requires_code, relation),
    CONSTRAINT prereq_edges_relation_check
        CHECK (relation IN ('prereq', 'coreq'))
);

CREATE INDEX prereq_edges_requires_idx ON prereq_edges (requires_code);


CREATE TABLE credit_exclusions (
    code_a      TEXT NOT NULL,
    code_b      TEXT NOT NULL,
    source_url  TEXT,
    note        TEXT,
    PRIMARY KEY (code_a, code_b),
    CONSTRAINT credit_exclusions_order_check CHECK (code_a < code_b)
);


CREATE TABLE policy_chunks (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_url      TEXT        NOT NULL,
    doc_title       TEXT,
    section_path    TEXT,
    chunk_index     INT         NOT NULL,
    content         TEXT        NOT NULL,
    token_count     INT,
    embedding       vector(1536),
    embedded_at     TIMESTAMPTZ,
    calendar_year   TEXT        NOT NULL
);

CREATE INDEX policy_chunks_source_idx ON policy_chunks (source_url);


CREATE TABLE query_logs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asked_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    question        TEXT        NOT NULL,
    route           TEXT,
    verdict         TEXT,
    latency_ms      INT,
    citations       JSONB,
    error           TEXT
);

CREATE INDEX query_logs_asked_at_idx ON query_logs (asked_at DESC);
