"""Database access for course requirement data.

Shared by the CLI and (later) the Flask API. Neither should write SQL.
"""

from dataclasses import dataclass
from typing import Any

from psycopg import sql

from core.db import connection as _connect


@dataclass
class Course:
    code: str
    title: str | None
    credits: float | None
    prereq_text: str | None
    prereq_tree: dict | None
    extraction_status: str
    source_url: str


_COLUMNS = """code, title, credits, prereq_text, prereq_tree,
              extraction_status, source_url"""


def get_course(code: str) -> Course | None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT code, title, credits, prereq_text, prereq_tree, "
            "extraction_status, source_url FROM courses WHERE code = %s",
            (code,),
        )
        row = cur.fetchone()
    return Course(**row) if row else None


def list_courses(subject: str | None = None,
                 level_min: int | None = None) -> list[Course]:
    clauses = [sql.SQL("TRUE")]
    params: list[Any] = []
    if subject:
        clauses.append(sql.SQL("subject = %s"))
        params.append(subject.upper())
    if level_min:
        clauses.append(sql.SQL("number::int >= %s"))
        params.append(level_min)

    query = sql.SQL(
        "SELECT code, title, credits, prereq_text, prereq_tree, "
        "extraction_status, source_url FROM courses WHERE {} "
        "ORDER BY subject, number"
    ).format(sql.SQL(" AND ").join(clauses))

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return [Course(**r) for r in rows]


def suggest_codes(partial: str, limit: int = 5) -> list[str]:
    """Close matches for a code the user may have mistyped."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT code FROM courses WHERE code LIKE %s ORDER BY code LIMIT %s",
            (f"{partial.split()[0]}%", limit),
        )
        return [r["code"] for r in cur.fetchall()]
