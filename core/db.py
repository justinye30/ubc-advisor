"""One Postgres connection pool per process.

Every module that touches the database (repo, graph, retrieval, query
logging) borrows from this pool instead of opening its own connection.
Before this, one question could open four or five connections; under a
threaded web server that multiplies by the number of concurrent requests
and runs into Postgres' max_connections.

Usage is the same shape as before:

    with connection() as conn:
        conn.execute(...)

Leaving the block commits (or rolls back on an exception) and returns the
connection to the pool instead of closing it.
"""

import atexit
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

# Per process. Gunicorn runs WEB_WORKERS processes, each with its own pool,
# so the database sees up to WEB_WORKERS * DB_POOL_MAX connections.
POOL_MIN = int(os.environ.get("DB_POOL_MIN", "1"))
POOL_MAX = int(os.environ.get("DB_POOL_MAX", "4"))
POOL_TIMEOUT = float(os.environ.get("DB_POOL_TIMEOUT", "10"))       # wait for a free connection
STATEMENT_TIMEOUT_MS = int(os.environ.get("DB_STATEMENT_TIMEOUT_MS", "5000"))

_pool: ConnectionPool | None = None
_lock = threading.Lock()


def get_pool() -> ConnectionPool:
    """Create the pool on first use, not at import.

    Lazy creation matters under gunicorn: workers are forked from a parent
    process, and a pool opened before the fork would share sockets between
    processes. Created on first use, each worker gets its own.
    """
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:          # another thread may have won the race
                _pool = ConnectionPool(
                    os.environ["DATABASE_URL"],
                    min_size=POOL_MIN,
                    max_size=POOL_MAX,
                    timeout=POOL_TIMEOUT,
                    kwargs={
                        "row_factory": dict_row,
                        "options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
                    },
                    # Test each connection before handing it out: RDS and
                    # NAT/idle timeouts silently drop connections that sat idle.
                    check=ConnectionPool.check_connection,
                    name="advisor",
                    open=True,
                )
                atexit.register(close_pool)
    return _pool


@contextmanager
def connection() -> Iterator[psycopg.Connection[DictRow]]:
    with get_pool().connection() as conn:
        yield conn  # type: ignore[misc]


def close_pool() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None


def pool_stats() -> dict:
    """Pool counters for the readiness endpoint; empty if no pool yet."""
    return _pool.get_stats() if _pool is not None else {}
