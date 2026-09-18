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

## Router (Week 2)

- **Classification is a separate call from answering.** A misroute surfaces as
  a visible routing error, not a fluent wrong answer.
- **Model: claude-haiku-4-5-20251001 with structured output** (JSON schema,
  enum-constrained intent). Pinned dated model so eval results stay
  comparable. The pinned SDK exposes no temperature parameter, so stability
  is measured (`--runs 2`) rather than assumed.
- **Five intents: eligibility, policy, path, unlock, out_of_scope.** Boundary
  rule: classify by the kind of answer needed, not by whether a course code
  appears. Out-of-scope carries a scope reason (advice, course_content,
  registration, personal_record, other_institution, unrelated), each with a
  fixed refusal template — refusals are designed, not generated.
- **Known gaps:** "what is CPSC X about" routes out of scope (descriptions
  exist in `courses` but have no handler yet); mixed-intent questions get one
  route.
- **`agent/` holds everything that calls an LLM; `core/` never does.** The
  eligibility rule is enforced by package boundaries.
- **LangGraph StateGraph:** classify → conditional edge → one node per intent,
  plus a `failed` node for RouteError/API errors. Unexpected exceptions still
  raise. Classifier and handlers are injectable for tests.
- **Handlers return structured facts with source URLs, never prose.** Until
  Step 13 they use only full course codes and no transcript, and say so
  (`needs_course`, `requirements_only`).
- **Every question is logged** to query_logs (route, status, latency,
  citations); logging failures never break an answer.
- **PROMPT_VERSION** hashes model + prompt + schema; saved with every eval run.
- **Routing eval: 40 questions, 8 per intent, 8 traps.** Baseline (prompt
  ______): accuracy __%, pulled into eligibility __, refusal recall __%,
  false refusals __, scope reason __%, traps __/8, unstable across 2 runs __.

- **Prompt examples never overlap the eval set.** The first draft reused most
  eval questions as prompt examples, which would have measured recall of the
  examples, not routing. Rewritten before any measurement (prompt d3b7ce465d →
  ec765835e8); a test fails if prompt and eval share course codes.

- **Routing baseline (prompt 78d3de4c68):** accuracy 85–88% across runs;
  eligibility/unlock/out_of_scope recall 100%, path 88–100%, **policy 25–50%**;
  pulled into eligibility 0–1; refusal recall 100%; **false refusals 4–6**;
  6 of 40 questions unstable across 2 runs (all policy, plus path-before).
  The predicted failure (code-bearing questions pulled into eligibility)
  barely occurred; the real failure was the opposite — over-refusing policy.
- **Diagnosis:** rationales named the question "a policy question" and then
  chose out_of_scope. Causes: policy was the only intent without examples;
  "standing"/"registration" appeared in both policy and out-of-scope reasons;
  out_of_scope was framed as "everything else."
- **Fix:** policy examples on topics the eval doesn't test, explicit
  boundaries on the colliding scope reasons, out_of_scope as last resort
  (rule 0). Prompt → ______.
- **The 40-question set is now a dev set.** A 12-question holdout
  (`routing_holdout.yaml`) was written before measuring the fix and is not
  to be tuned on. Results: dev ___, holdout ___.
- **path-before left as a known ambiguous boundary** ("what do I need before
  X" reads as either direct prerequisites or a chain); not tuned for.

- **Fix:** ... Prompt → f8112e3097.
- **Results (f8112e3097):** dev 98% (39/40; policy 100%, false refusals 0,
  refusal recall 100%, traps 8/8, 1 unstable — path-before); holdout 100%
  (12/12, policy 6/6, traps 3/3, stable across 3 runs). The only remaining
  miss is the known-ambiguous path-before, left untuned.
- **Both routing sets are now spent for tuning.** Further prompt changes
  need fresh questions; Step 16 is the held-out measurement.

## Entity extraction (Week 2)

- **The LLM reads; deterministic code decides what to believe.** The model
  returns each course with the exact text it came from (`as_written`).
  Validation rejects anything not in the question, resolves bare numbers
  against the catalogue (one match: accept and say so; several: ask),
  rejects Okanagan codes even when the suffix was dropped, and requires
  grades and year to appear in the question.
- **Nothing is dropped silently.** Every result carries `assumptions`
  (stated in the answer), `rejected` (model output we didn't believe), and
  `unused` (codes written but not extracted).
- **"History given" is separate from "courses listed."** No history →
  requirements only, never a verdict against an empty transcript. A failed
  course or "nothing yet" still counts as history. In-progress courses
  count as completed, with a stated assumption.
- **Letter grades are percentage bands** (UBC Vancouver scale). MIN_GRADE is
  satisfied if the band clears the bar, not satisfied if it falls short,
  and INDETERMINATE if it straddles.
- **Fixed a Week 1 MIN_GRADE bug:** one failing graded option plus one
  ungraded option returned NOT_SATISFIED; now INDETERMINATE.
- **Only eligibility/path/unlock pay for extraction**; policy and
  out-of-scope skip it. Ambiguity routes to a `clarify` node.
- **Program names are matched only against PROGRAM nodes that exist in the
  trees**, loaded from the database.
- **Structured-output constraints shaped the schema:** all fields required
  (empty string / 0 as sentinels), no union types; enum values compared
  case-insensitively (router fixed; prompt version unchanged).
- **Sweep logic moved to core/sweep.py** for the agent (CLI still has its own
  copy — cleanup pending).

- **Extraction baseline:** 24/25 exact; 0 extra codes reached a verdict;
  injection question held. The one miss was the validator: it required
  `as_written` verbatim, and the model wrote "CPSC 121" for a bare "121",
  so two real completed courses were dropped — which would have produced a
  wrong "missing prerequisite" verdict.
- **Fix:** course numbers are grounded in the question itself. A number is
  usable if it appears bare or next to the same subject; a number written
  next to a different subject can't be borrowed; numbers followed by % are
  grades. `as_written` is kept in the schema but not trusted.
- **Run-to-run variation shows up in extraction too:** `not-yet-taken`
  passed once and returned no target the next run (model, not validator).
- **Missing-target safety net (graph, not extractor):** if the intent needs a
  target, none was extracted, and exactly one full code in the question went
  unused, it becomes the target with a stated assumption. Not applied when
  it would be a guess (several unused codes) or when an eligibility question
  with history is really a sweep. Kept out of `extract()` so the eval still
  measures the raw model + validator.

- **Extraction results after the grounding fix:** dev 24/25 (the one miss was
  run-to-run variation, now covered by the missing-target safety net);
  holdout 10/10, including the cross-subject borrowing and "100%" traps;
  0 extra codes reached a verdict on either set.

## Composer (Week 2)

- **The verdict sentence is fixed text, never model output.** "Yes / Not yet /
  I can't tell" is chosen from the evaluator's state (`VERDICT_SENTENCE`), so
  a fluent model can't turn INDETERMINATE into "you're good to go". Every
  "yes" says "based on what you've told me."
- **The model writes only the explanation, as sentences that each cite fact
  ids:** [you] what the student said and how we read it, [check] computed
  results, [S#] quoted calendar sources. The question is labelled "not a
  source." Code numbers the calendar citations and adds sources and the
  disclaimer.
- **Templates for everything that needs no model:** refusals, clarifications,
  needs-course, not-found, no-results, errors (internal messages never shown).
- **Structural validation only in this step** (non-empty, ≤6 sentences, every
  sentence cites known ids); one retry that shows the model its rejected
  answer; then a deterministic template explanation. Every answer records
  `composed_by` and `problems`.
- **Drift is measured, not yet enforced:** advice phrases, codes/bare
  numbers not in the facts, percentages/credits not in the facts, claims
  contradicting the verdict. Step 15 enforces these and re-measures.
- **Model: Haiku 4.5** (COMPOSER_MODEL), to be revisited if the eval shows
  weak explanations.
- **query_logs.citations now records sources the answer actually cited.**
- **Composer eval: 15 cases**, real handlers on fixed inputs, no model
  scoring. Baseline: composed by llm __ / fallback __ / retries __;
  drift: advice __, ungrounded codes __, numbers __, verdict conflicts __.

- **First real answers exposed semantic drift the surface checks missed.**
  The 61%-in-MATH-226 answer (INDETERMINATE) invented a remedy ("retake MATH
  226", which the repeat policy forbids for passed courses) and described the
  unverifiable MATH_O 220 as missing. No Step 14 check flagged it.
- **Fixes:** the INDETERMINATE verdict now names what can't be checked, as
  fixed text; facts mark those as "unknown, not missing"; the prompt forbids
  gap-closing suggestions and referrals; checks add "need to take/complete/
  retake…", advisor referrals, and ungrounded remedy words; citing [check]
  links the page the check was computed from, so unlock answers keep a source.
- `elig-cant-tell` is a development case for these fixes; the other 14
  composer cases form the baseline.

- **Composer baseline (Haiku 4.5, prompt after fixes):** 15/15 composed by
  the model, no fallbacks or retries; advice, invented codes, numbers and
  remedies all 0 in one run. Rerun with `--runs 3`: ______.
- **The verdict-conflict check was too blunt:** it flagged true claims about
  other courses ("you can take CPSC 221 now" on the way to CPSC 404). Now
  sentence-level and scoped to the verdict's course (or no course named).
- **Composition varies run to run.** The same can't-tell case produced "You
  don't meet the stated prerequisites for CPSC 221" in one run (a conflict
  with the INDETERMINATE verdict) and nothing flaggable in another. The
  prompt reduces but doesn't eliminate this; Step 15 enforces it.

- **Composer baseline (2 evals × 3 runs × 15 cases = 90 answers):** all
  composed by the model, no fallbacks; 0 invented codes, numbers, or
  remedies. Drift in 4–5/15 cases: advice flags 3–6 (policy-retake,
  policy-lop), verdict-conflict flags 5–6 (elig-year, elig-cant-tell,
  path-personal). Run-to-run variation makes this a range, not a number.
- **Flags to classify before Step 15:** real drift vs. true partial claims
  ("you meet the year requirement") vs. calendar wording echoed from a cited
  source ("consult Science Advising").

- **Composer flags classified (all 8 from the saved baseline):** 5 verdict
  conflicts were false positives — a negation ("cannot confirm you meet"),
  hedges ("whether you can take"), a true partial claim ("you satisfy two of
  the four requirements"); 3 advice flags were calendar wording the answer
  cited ("they should consult academic advisors", "present your case to an
  Advisor in Science Advising").
- **One real error, caught for the wrong reason:** path-personal said CPEN
  212 "can be taken immediately". It can't — the path tree's note
  "(another option is ready)" meant a different option in its group was
  ready, and the model misread it. A facts-labelling problem, not a
  phrasing one.
- **Conclusion for Step 15:** phrase-matching checks are too noisy to
  enforce and blind to factual errors. The guard should check claims
  against structured facts (readiness lists), treat hedges/negations/partial
  claims as non-claims, judge advice wording against the cited source's
  text, and fix the ambiguous tree label.

  ## Citation guard (Week 2)

- **Designed from Step 14's classified flags.** Phrase matching was too noisy
  to enforce: negations, hedges and partial claims aren't eligibility claims;
  calendar wording in a cited source isn't the assistant's advice; and the one
  real error ("CPEN 212 … you can take immediately") needed the structured
  ready-now list to refute.
- **Claims are checked clause by clause** (dashes, semicolons, contrast words,
  relative clauses); "both of which…" borrows the listed courses, not the
  target.
- **Checked against structured truth:** target, verdicts, the student's
  history, and which courses may be called takeable (path ready-now;
  personal-unlock newly/already eligible; sweep eligible/no-prereq;
  satisfied targets; nothing for a history-less unlock).
- **Violation kinds:** invented code/number/remedy, ungrounded advice
  (allowed only when the cited source says it), contradicts verdict, not
  ready, invented history, contradicts history.
- **Codes/numbers are grounded against all facts; advice against the cited
  source only** — citations are sometimes loose, but for advice the citation
  is the justification.
- **Enforcement:** regenerate once with the violations explained; otherwise
  trim offending sentences from the better attempt; otherwise the template
  explanation. Every answer records the action and what was caught.
- **Fixed the label behind the real error:** "(not needed now: another option
  is ready)", with the facts legend saying the course is neither ready nor
  required.
- **The eight Step 14 sentences are regression tests:** the guard flags
  exactly the one real error.
- **Results:** rescored Step 14 baseline: __ of __ sentences flagged (all
  real? __). Guarded, 3 runs × 15 cases: passed __ / regenerated __ /
  trimmed __ / fallback __; caught __ (by kind: __); left after guard 0.

- **First rescore of the Step 14 baseline:** 4 of 130 sentences flagged —
  2 real (CPEN 212 "can take immediately"; "you can take CPSC 221, DSCI 221"
  to a student with no history) and 2 false positives ("you meet the first
  prerequisite" — a partial claim; "the calendar requires CPSC 121, MATH 220
  … and you completed CPSC 210" — history applied to every code in the
  clause).
- **Fixes:** ordinals/quantifiers after the verb mark partial claims ("all"
  stays full); history and availability claims apply only to the verb's
  courses (after it; before it for "open to you"/"that you can take";
  borrowed for "both of which"); "unlike / rather than / instead of" split
  clauses. All four sentences are regression tests. Rescore after fixes:
  2 of 130, both real.

- **Rescore after fixes:** 2 of 130 baseline sentences flagged, both real —
  the "before": 2 of 45 Step 14 answers would have shipped an error.
- **Guarded eval (2 × 3 runs × 15 cases = 90 answers):** passed on first
  draft 82/90; regenerated 4; trimmed 4; fallback 0. Draft sentences caught:
  6 and 3 (kinds: contradicts verdict, contradicts history, invented
  history, invented remedy, not ready). **Violations shipped: 0.**
- **Precision on unseen flags (run B):** __ real / __ false positive.
- **Cost:** one extra composer call on ~9% of answers.

- **Guarded eval, flags read by hand (run B):** 1 real ("You cannot take
  CPSC 221" under a can't-tell verdict — regenerated cleanly) and 2 false
  positives, both from back-references borrowing too much: "which is not
  among the courses you've completed" took all five courses in the clause
  (and ignored "not"); "both of which you're ready to take" took CPSC 304
  along with CPSC 221/DSCI 221. The second trimmed a true, useful sentence
  from a shipped answer.
- **Fix:** back-references borrow only the trailing list of the previous
  clause; negated clauses make no positive history claim. All three
  sentences are regression tests.
- **Across all 15 hand-read flags, the guard now marks exactly the real
  problems** — but those flags informed the rules, so precision on unseen
  flags is still unmeasured (Step 16).
- **Summary:** 90 guarded answers, 0 violations shipped; the guard acted on
  ~9%; before the guard, 2 of 45 Step 14 answers would have shipped a
  factual error.

## End-to-end eval (Week 2, Step 16)

- **50 questions through the full graph:** 40 answerable (incl. 2 where
  "which course?" is correct), 10 to decline. No wording reused from earlier
  eval sets; no course codes shared with prompt examples (tested).
- **Answer correctness uses gold inputs, not gold text:** each answerable
  question lists the intent, courses, history, grades and year a careful
  reader would extract; the runner feeds those to the same handlers and
  compares results with what the pipeline reached from the English. Policy
  answers are checked on cited page and key facts. The core's own accuracy is
  Week 1's golden set; `--audit` spot-checks it here.
- **Declining** = refusal, course not found, no results, "which course?"
  with nothing to go on, or an answer saying the calendar doesn't cover it.
  Retrieval always returns 5 chunks, so d09 (tuition) tests the composer's
  "sources don't address it" rule.
- **pipeline_version()** hashes all prompts, schemas and models; printed and
  saved with every run.
- **Fixed:** a Voyage outage in the policy handler crashed the whole request;
  now it's an error answer. The eval also survives a crashing question.
- **Guard records flagged draft sentences,** so fresh guard catches can be
  read by hand — the independent precision check Step 15 lacked.
- **Audit:** __ gold results checked against the calendar; __ disagreements.
- **Baseline (pipeline ______):** routing __/47; answer correctness __/40;
  refusal correctness __/10; false refusals __; guard: passed __ / regenerated
  __ / trimmed __ / fallback __; guard catches read: __ real, __ false
  positive; latency p50 __s, p95 __s. Failures: ______.

- **First end-to-end baseline (pipeline 02e8cfbcfe, two runs):** routing 47/47
  and 46/47; answer correctness 39/40 and 37/40; refusal correctness 8/10
  both runs; false refusals 1–2; guard passed 37–38, regenerated 1–2, no
  trims or fallbacks; latency p50 ~7s, p95 ~22s (policy only, from the
  Voyage free-tier throttle).
- **Audit:** 23 of 26 gold results confirmed against the calendar; the three
  oddities (CPSC 420's prereq_text, MATH 220 in an unlock, an empty sweep
  line) were checked and are fine.
- **Guard precision on fresh flags: 1 real, 2 false positives.** Real: an
  answer claiming MATH 254/STAT 251/MATH 318 were "available to you now"
  when they weren't (regenerated). False positives: a pronoun claim about a
  ready course ("you're eligible to take it now"), and "before you can take
  CPSC 213" read as availability.
- **Fixes:** eligibility returns `course_not_found` like the other handlers
  (d07/d08 now read as declines); an unlock with a lone in-progress course
  uses it as the target (q25); "before" is a hedge; a positive claim beside a
  ready non-target course isn't a verdict claim. All four are regression
  tests.
- **Known instability:** "what comes after 200?" (q16) alternates between a
  clarification and a refusal. Left untuned.

- **After the first fixes:** refusal correctness 10/10 (unknown courses now
  return `course_not_found`); routing 46/47 and answer correctness 38/40,
  both limited by q16 ("what comes after 200?", still unstable) and q25.
- **q25 was a real bug:** an unlock question was evaluated against a
  transcript that already contained the target (in-progress counts as
  completed), so "newly eligible" was empty. The before-state now excludes
  the target, and the opening sentence says "Finishing X…" when the student
  already has it.
- **Guard precision across the e2e exercise: 2 real, 4 false positives**
  (pronoun reference, "before you can take", possessive mention, borrowed
  codes). All are regression tests. Recall on real errors was good from the
  start; precision needed five rounds of reading flags by hand.
- **q33 label:** the answer cites the transfer-credit page rather than
  general degree requirements, and every claim is grounded there. Label
  widened — the check is "cites a page that supports the answer".
- **Policy latency (~20s) is the Voyage free-tier throttle** (EMBED_RPM=3),
  not the pipeline; every other route is 5–10s.

- **Two label errors found by reading answers, not system failures:**
  q33 expected only `general-degree-requirements`, but the answer correctly
  turns on transfer-credit and upper-level limits (label widened); q38
  assumed the Lower-level Requirements page caps first-year courses — it
  doesn't (lab science, additional courses, foundational only), so the corpus
  can't answer it and the question now tests scoped "not in the sections I
  found" phrasing.
- **New violation kind, "unverifiable absence":** an answer said "the
  calendar does not specify a cap" from five retrieved sections. Absence
  can't be checked that way, so the composer must scope such statements and
  the guard catches unscoped ones. Pipeline → a15e80f86f.

- **Final end-to-end baseline (pipeline a15e80f86f):** routing 46/47;
  answer correctness 38/40; refusal correctness 10/10; false refusals 1;
  guard passed 37, regenerated 1, 0 violations shipped; latency p50 4.4s,
  p95 21.3s (policy only, from the embedding throttle).
- **Guard catches in the final runs:** "at most 6 credits numbered 500+"
  (a real UBC rule the model knew but the retrieved sections didn't state)
  and "the remaining 18 credits available from other faculties" (arithmetic
  plus an unsupported policy claim). Both regenerated.
- **Three of my 40 labels were wrong** and were corrected by reading the
  answers: q33's page list, and q38 twice (which page, then which phrasing).
  The eval found bugs in the system and in itself.
- **Known limits:** q16's bare-number ambiguity is unresolved by design;
  guard precision was tuned against flags read by hand, so precision on
  unseen phrasings is sampled, not proven.