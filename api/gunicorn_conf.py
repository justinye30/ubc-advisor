"""Production server settings. Every value can be overridden by env var."""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# Requests spend most of their time waiting on the Anthropic API, so threads
# (not more processes) are what buy concurrency. Each worker process has its
# own connection pool: keep DB_POOL_MAX == WEB_THREADS, since one request
# holds at most one connection at a time.
workers = int(os.environ.get("WEB_WORKERS", "2"))
worker_class = "gthread"
threads = int(os.environ.get("WEB_THREADS", "4"))

# With gthread, this restarts a worker whose main loop stops responding. It
# is NOT a per-request deadline; per-call timeouts (LLM_TIMEOUT, Voyage,
# statement_timeout) are what bound a single request.
timeout = 120
graceful_timeout = 30

# Must exceed the load balancer's idle timeout, or the ALB can reuse a
# connection gunicorn just closed and return a 502. Step 19 sets the ALB to 120s.
keepalive = 125

accesslog = None        # the app logs each request with its request_id
errorlog = "-"

# Don't import the app before forking: each worker must build its own pool.
preload_app = False
