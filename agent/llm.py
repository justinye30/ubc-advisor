"""The one place Anthropic clients are made.

The SDK's default timeout is 10 minutes with 2 retries: fine for a batch
script, wrong for a web request someone is watching. A timeout raises
anthropic.APITimeoutError, a subclass of APIError, which the graph and the
composer already catch: routing/extraction fail cleanly, the composer falls
back to its template.

Client config is not part of pipeline_version(): it changes how long we
wait, not what the model is asked.
"""

import os

import anthropic

LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "15"))       # seconds per attempt
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "1"))


def new_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(timeout=LLM_TIMEOUT, max_retries=LLM_MAX_RETRIES)
