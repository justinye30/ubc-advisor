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

- **Extraction is not deterministic.** Anthropic SDK v1.0 removed the
  `temperature` parameter, so identical input can produce slightly different
  trees across runs. Trees are extracted once and stored; evals measure the
  stored artifact. Re-extraction requires an explicit `--redo`.

- **Coverage-check false positives are not all UNPARSED.** In several cases the
  model correctly excluded courses that the calendar marks as *recommended*
  rather than required (e.g. "MATH 200 (or MATH 217 or MATH 226) is
  recommended"). The regex check cannot distinguish requirement text from
  advisory text, so these flag as "codes in text but not tree" despite being
  correct extractions. Reviewed manually; left flagged as informational.

- **Corequisites nested inside prerequisite disjunctions become UNPARSED.**
  Three courses have branches like "or (d) SCIE_V 001 as a corequisite."
  Concurrent enrolment cannot be verified from a completed-courses transcript,
  so a dedicated node type would add schema surface without enabling a correct
  answer. UNPARSED yields INDETERMINATE with the clause quoted, which is honest.
  
- **Sweep hides 500-level courses by default.** Graduate courses are not open
  to undergraduates, but the calendar does not encode that as a prerequisite —
  so they evaluated as "eligible" for a student with no transcript. The 500+
  cutoff is a heuristic, not something derived from the data.
- **Absence of a prerequisite sentence is not evidence of open registration.**
  405 of 718 courses have no listed prerequisite; many are still restricted by
  program, year, or instructor approval. Reported under a separate heading
  rather than as "eligible."

## Policy corpus (Week 2)

- **13 pages, all B.Sc.-scoped.** Program requirements plus the regulations
  pages covering registration, repeating courses, credit, and standing. Kept
  small on purpose: every extra page is another chance to retrieve the wrong
  chunk.
- **Credit Exclusion Lists excluded from the vector corpus.** Hundreds of lines
  of code pairs, not prose. That's structured data and belongs in
  `credit_exclusions`, looked up deterministically, same as prerequisite trees.
- **Chunks split on headings, never inside a block.** A paragraph, list, or
  table is atomic. Long sections split between blocks, with the last small
  prose block repeated as overlap. Tables are never split and never carried
  as overlap.
- **Tables stay whole because the exceptions are in the footnotes.** e.g. the
  CS Major's STAT_V 251 substitution rule is footnote 2 of the requirements
  table. Cost: a few oversize chunks on the combined-major tables. Revisit if
  Step 10 recall suffers.
- **Footnote superscripts rewritten as ` [n]` before text extraction.**
  Flattening `CPSC_V 210<sup>1</sup>` yields `CPSC_V 2101`, a different
  course code. Checked by a SQL query for 4-digit course numbers.
- **Section path is embedded in chunk content**, not just stored alongside.
  Table rows are meaningless to an embedding model without their heading.
- **Chunk text keeps calendar code formatting (`CPSC_V`).** Normalization
  happens at comparison time (entity extraction, citation guard).
- **Token counts are chars/4 estimates** until the embedding model is chosen.
- **Page chrome is detected, not assumed absent.** Canary strings ("Main
  navigation") in any chunk fail the run.
- **Terms of Use:** 13 additional requests at the 10s robots.txt delay;
  same clause (f) reasoning as the subject index fetch.

## Embeddings and retrieval

- **Model: Voyage `voyage-4`, 1024 dims.** Anthropic doesn't offer an
  embedding model and its docs point to Voyage. Free tier covers this corpus
  many times over; query/document input types suit short-question-vs-long-
  passage retrieval; the 4-series shared embedding space allows a cheaper
  query model later without re-embedding.
- **`policy_chunks.embedding` resized 1536 → 1024** (003). Free while every
  row was NULL; the 1536 in 002 was a placeholder pending this decision.
- **Called over REST with `requests`**, not the voyageai SDK: no new
  dependency to keep compatible with Python 3.14.
- **`embedding_model` stored per row.** Search filters on it; the embed
  script refuses to mix models without `--redo`. Vectors from different
  models are not comparable and fail silently if mixed.
- **Truncation disabled.** An over-long chunk errors instead of being cut.
- **HNSW index created but unused at this size** — the planner prefers an
  exact scan over ~100 rows, so recall numbers reflect the embeddings, not
  index approximation.
- **Hybrid = vector + course-code exact match, fused with RRF (k=60).**
  Plain full-text search over the whole question failed in testing: Postgres
  ANDs every term, so incidental words ("something") kill matches. The
  lexical leg only searches for course codes, using subjects found in the
  corpus, and does nothing for questions without one.
- **Retrieval eval: 15 questions, labels checked against the DB before scoring.**
  Baseline (voyage-4, 105 chunks): vector recall@1 0.80,
  recall@5 1.00, MRR@10 0.88; hybrid recall@1 0.87, recall@5 1.00,
  MRR@10 0.93. The one difference: stat-251-substitute went from rank 5
  (vector) to rank 1 (hybrid), the literal-code weakness predicted in the
  plan. No paraphrase question changed.
- **Decision: hybrid is the default.**
  Caveat: recall@5 is at ceiling on a 105-chunk corpus; recall@1 and MRR
  are the discriminating numbers going forward.
- **Known retrieval weak spots (not tuned — test set):** `residency` ranks
  Credit Loads above the 50% rule (shared "at UBC" wording);
  `letter-of-permission` ranks general Transfer Credit first, which is a
  genuinely ambiguous reading of "transfer back." Both are cases for the
  Step 14 composer: two plausible chunks, one right answer.

## Graph queries

- **The graph narrows; the evaluator decides.** prereq_edges flattens trees
  and loses which alternatives go together, so it's used to find candidates
  (reverse lookups) and draw structure. "Can this student take X" is always
  evaluate() on the full tree. `unlocks --have` re-evaluates each dependent
  with and without the course, so a grade threshold on the new course lands
  in "needs confirmation" rather than "unlocked."
- **Fixed edge flattening: a code is optional only if every occurrence is.**
  The old edges() + ON CONFLICT DO NOTHING kept whichever occurrence came
  first, so ALL_OF(ONE_OF(A,B), A) stored A as optional. Rebuilt edges from
  stored trees (no LLM call): +__ / -__ edges changed on real data.
- **Edges are derived data.** `ingest.rebuild_edges` regenerates them from
  prereq_tree deterministically, reports the diff, dead-end codes (__),
  self-references, and 2-cycles.
- **Transitive walk uses UNION, not UNION ALL + path array.** UNION
  deduplicates as it recurses, so work is bounded by distinct edges and
  cycles terminate naturally. On a synthetic 8-level graph (20 courses per
  level, 3 prereqs each) the path-array version produced 3,279 rows for 252
  edges (12 ms, growing ~3x per level); UNION produced 253 in 2 ms with a
  cycle added.
- **"Required" is transitive only through required edges.** One optional
  hop breaks the chain. `path` lists alternatives without choosing between
  them — picking a route is advice, not lookup.
- **Walk stops beneath completed courses.** Their prerequisites no longer
  matter to the student.
- **Known gaps:** no coreq edges (coreq_tree never extracted); credit
  exclusions not applied; graph completeness is capped by extraction
  (flagged courses are marked in `path` output).

- **Dead ends in the graph (98 codes referenced but not in `courses`):**
  81 out-of-scope subjects (expected); 10 BC high-school courses (PREC 12,
  PHYS 12, …) that already evaluate as INDETERMINATE via is_in_scope's
  three-digit rule, now with their own reason text; 7 in-scope codes
  (CPEN 322, CPSC 261, ENGL 112, PHYS 257, PHYS 313, SCIE 120, STAT 241)
  verified by hand as retired and recorded in `KNOWN_RETIRED`.
  rebuild_edges warns on any in-scope dead end not in that set — the
  signal for a parser gap.
- **Edge optionality on real data:** 1,320 edges, 159 required / 1,161
  optional (88%). No single-child ONE_OFs, so the ratio reflects the
  calendar's "one of" lists, not an extraction artifact. The flattening fix
  changed 0 edges (preventive).