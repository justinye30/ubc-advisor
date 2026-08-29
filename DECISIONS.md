# Design Decisions

Running log of choices made and why. Newest at the bottom.

## Scope

- **Campus:** UBC Vancouver only. Okanagan uses parallel `_O` course codes and
  would roughly double the extraction surface for no added value to the target user.
- **Subjects:** CPSC, MATH, STAT, DSCI, CPEN, PHYS, ENGL, WRDS, SCIE. This is the
  realistic universe for a CS student (~400-600 courses, not ~10,000).
- **Programs:** BSc Computer Science Major first. BCS, COGS, and Minor later.
- **Calendar year:** pinned via `CALENDAR_YEAR` in `.env`. Requirements change
  annually; pinning makes extraction reproducible and citations honest.

## Core architecture

- **The LLM never decides eligibility.** It has exactly two jobs: parsing
  prerequisite prose into a structured tree (offline, verified against a golden
  set), and phrasing an already-computed result. The verdict itself comes from
  deterministic Python evaluating a boolean tree.

  Rationale: real UBC prerequisites are nested boolean expressions with grade
  thresholds and credit-count clauses. Vector search over prose retrieves a chunk
  mentioning the right course codes and lets the model improvise the relationship
  between them. It is right most of the time and confidently wrong the rest,
  which is worse than useless for something a student registers on.

- **Requirements stored as JSONB boolean trees**, not normalized tables.
  Two-level `prereq_groups`/`prereq_options` normalization only expresses flat
  DNF. Actual calendar text nests deeper than that. A flattened `prereq_edges`
  table is kept alongside for graph traversal and visualization only.

- **Tri-state evaluation:** SATISFIED / NOT_SATISFIED / INDETERMINATE.
  The calendar states that prerequisites imply "or the equivalent" and "or the
  consent of the instructor," and may be waived at instructor discretion. So
  eligibility is not a mechanical boolean by UBC's own rules. Permission clauses,
  unparsed text, transfer credit, and missing grades all resolve to INDETERMINATE
  rather than a guess.

- **`prereq_text` is stored verbatim** and never modified. It is the ground truth
  for auditing extraction accuracy and is shown to the user alongside any verdict.

## Infrastructure

- **Python 3.14** locally and in the container, matched deliberately. Package
  resolution differs across interpreter versions; a mismatch produces
  "works locally, fails in Docker" bugs.
- **`pgvector/pgvector:pg16`** rather than stock `postgres:16` — avoids compiling
  the extension by hand.
- **Migrations via `/docker-entrypoint-initdb.d`.** These run only when the data
  volume is empty, so schema changes require `make reset`. Acceptable because the
  database is fully rebuildable from scraped source data. A real migration tool
  (Alembic) would be warranted if it ever held data that could not be regenerated.
- **Dependencies pinned via `pip freeze`.** Initial pins targeted Python 3.12 and
  `lxml` had no 3.14 wheel, forcing a source build that failed on missing libxml2
  headers. Loosened, resolved, re-pinned.

## Course code normalization

- **Canonical form is `CPSC 221`** — subject, single space, number. This is what
  students type, which matters for query-time entity extraction.
- **`_V` is stripped; `_O` marks out-of-scope.** The suffixes disambiguate campus,
  and real prerequisite text mixes them in one clause (e.g. "one of CPSC_V 121,
  MATH_V 220, MATH_O 220"). Naive stripping would collapse `MATH_V 220` and
  `MATH_O 220` into the same code and silently merge two distinct options.
  Okanagan codes become `OUT_OF_SCOPE` nodes in the tree, which resolve to
  INDETERMINATE rather than being dropped.
- **One normalization function** in `core/codes.py`, called by the course parser,
  the extraction validator, and query-time entity extraction alike. Never
  normalized ad hoc at a call site — divergent forms would produce duplicate rows
  and orphaned graph edges.
- **Enforced at the database boundary** by a CHECK constraint on `courses.code`
  (`^[A-Z]{2,5} [0-9]{3}[A-Z]?$`). Even if a code path forgets to normalize,
  the insert fails loudly instead of corrupting the graph. Trailing `[A-Z]?`
  handles courses like MATH 100A.

## Schema

- **Verbatim source text is stored alongside every extraction.** `prereq_text` is
  never modified. It is the ground truth for auditing extraction accuracy, it
  lets us reprocess without re-scraping, and it is shown to the user next to any
  verdict.

- **`raw_pages` caches every fetch before parsing.** Parsing logic will be
  iterated on many times; the pages should be fetched once. `content_sha256`
  gives change detection when the calendar updates.

- **`prereq_edges` is derived, not authoritative.** It duplicates information
  already in `prereq_tree` — deliberate denormalization, because trees answer
  "is this student eligible" while a flat edge table answers "what unlocks if I
  take 213." Regenerated from the tree after extraction; never hand-edited.
  `is_optional` marks edges under a `ONE_OF`, without which a graph view would
  wrongly imply every listed course is required.

- **No foreign key on `prereq_edges.requires_code`.** Prerequisites legitimately
  reference courses outside scope (Okanagan, unscraped subjects). A FK would
  reject those rows; we want the edge recorded as an INDETERMINATE signal.

- **`credits` is `NUMERIC`, not integer or float.** Some courses are 1.5 credits.
  Float is wrong for values that get summed and compared against thresholds in
  `MIN_CREDITS` evaluation.

- **`extraction_status` is a state machine** (`pending` → `no_prereq` / `parsed` /
  `flagged` → `human_verified`). `no_prereq` is distinct from `pending` so
  coverage metrics can tell "genuinely has none" from "not processed yet."

- **`policy_chunks.embedding` is `vector(1536)`.** Dimension must match the
  embedding model exactly and cannot be reinterpreted — changing models requires
  recreating the column. Model choice is deferred to Week 2; revisit this line
  when it is made.

- **HNSW index deferred.** Building a vector index on an empty table is
  pointless and pgvector builds more efficiently over existing data. Add as
  `003_vector_index.sql` once chunks are populated.

- **`query_logs` exists from day one.** Usage metrics cannot be backfilled, and
  "answered N queries for M students" is only claimable if logging predates
  launch. Question text is logged; transcripts and identifying data are not.
  Retention policy: TBD before any public launch, and disclosed in the README.

## Terms of Use (read 2026-08-29)

- **Clause (f), load:** 9 index requests at the robots.txt-specified 10s delay
  is not an "unreasonable or disproportionately large load." Fetching is fine.
- **Clause (a), redistribution:** grants a limited license for personal,
  non-commercial, unmodified use of short extracts. Reproducing, republishing,
  or re-disseminating requires prior written consent. A public tool serving
  parsed course data to other students falls outside this.
- **Decision:** built for personal use. Written consent requested from
  [department] on [date]; public launch deferred pending a response.
- **Scraped HTML is never committed** to the repo. Test fixtures use
  hand-written excerpts, not page dumps.

## Fetch strategy

- **Subject index pages only** (~9 requests). At the robots.txt-mandated 10s
  delay, individual course pages would be ~83 minutes per refresh vs ~90 seconds.
  Verified 2026-08-29 that index pages carry full untruncated prerequisite text,
  including the long CPSC 330 clause.
- **Citation URLs are constructed, never fetched.**
  `CPSC 221` -> `/course-descriptions/courses/cpscv-221`. Pattern verified
  against CPSC, MATH, and STAT.
- **`raw_pages.url` (index page fetched) and `courses.source_url` (per-course
  citation) are intentionally different values.** Not an inconsistency.
- **Golden set exception:** ~40 individual course pages fetched once to confirm
  index pages match individual pages.

## Metrics and honesty

- Usage numbers reported from `query_logs` only, never estimated or rounded up.
- The headline metric is extraction and answer accuracy against a hand-labeled
  eval set, not user count.

## Parsing

- **Subject pages are inconsistent about `<strong>` title wrappers.** CPSC and
  DSCI wrap course titles in `<strong>`; ENGL, MATH, PHYS, STAT do not. An
  initial parser that extracted `<strong>` and anchored the heading regex at `$`
  silently dropped 190 of 718 articles (ENGL lost two-thirds). Fixed by matching
  the code/credits prefix and treating the remainder as the title.
- **The anomaly counters caught this, not inspection.** Silent-skip parsing would
  have produced a plausible-looking 528-course database with no signal that a
  quarter of the corpus was missing. Every skip path increments a named counter.
- **Contact-hours markers (`[3-2-0]`) are absent from 63% of courses**, mostly
  humanities and seminars. The fallback split at the first `Prerequisite:` /
  `Corequisite:` keyword handles these; verified no requirement text leaks into
  `description`.
- **Credits may be ranges** (e.g. `(3-6)`); the lower bound is stored.

- **Grading-policy sentences are stripped in the parser, not the prompt.**
  74 of 313 courses appended "This course is not eligible for Credit/D/Fail
  grading" or a credit-exclusion note to their prerequisite. Deterministic
  removal is more reliable than instructing the model to ignore it, and saves
  tokens on every re-run.
- **Two courses (CPSC 320, STAT 200) reference the Faculty of Science credit
  exclusion list via a URL that UBC truncates in its own HTML.** These become
  EXTERNAL_LIST nodes resolving to INDETERMINATE. The full URL was reconstructed
  by hand.