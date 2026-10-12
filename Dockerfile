# syntax=docker/dockerfile:1

# ---------------------------------------------------------------- 1. web UI
# Node is only needed to build the UI. It never reaches the final image.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build


# ---------------------------------------------------------------- 2. app
FROM python:3.14-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# A normal user, uid 1000 to match the usual first user on Linux/WSL, so
# files the dev container writes into the bind-mounted repo stay yours.
RUN useradd --create-home --uid 1000 app
WORKDIR /app

# Dependencies first: this layer only rebuilds when requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Only what the server runs (see .dockerignore for what's left out).
COPY --chown=app:app agent/ agent/
COPY --chown=app:app api/ api/
COPY --chown=app:app core/ core/
COPY --from=web --chown=app:app /web/dist web/dist

USER app
EXPOSE 8000

# ECS reads this through the task definition's health check, not Docker's.
CMD ["gunicorn", "-c", "api/gunicorn_conf.py", "api.app:app"]
