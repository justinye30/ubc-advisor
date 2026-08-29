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
