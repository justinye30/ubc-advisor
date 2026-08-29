# UBC Degree Requirements Advisor

Ask whether you can take a course, and get an answer computed from the UBC
Academic Calendar with a citation to the exact source paragraph.

> **Unofficial.** This is a student project, not academic advising. Prerequisites
> may be waived at instructor discretion and the Calendar is the authoritative
> source. Confirm anything that matters with an academic advisor.

## Status

In development. Built for personal use — UBC's Terms of Use require written
consent to redistribute calendar content. See
[DECISIONS.md](DECISIONS.md).

## Stack

Python · Flask · PostgreSQL + pgvector · Docker · AWS (planned)

## Local setup

Requires Docker and `make`.

```bash
cp .env.example .env    # fill in ANTHROPIC_API_KEY when needed
make up
curl localhost:8000/health
```

| Command | Does |
|---|---|
| `make up` | Start the stack |
| `make down` | Stop, keep data |
| `make reset` | Destroy the volume and re-run migrations |
| `make psql` | Interactive database session |
| `make test` | Run tests |

## Design

See [DECISIONS.md](DECISIONS.md).
