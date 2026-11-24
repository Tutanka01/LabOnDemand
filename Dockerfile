# syntax=docker/dockerfile:1
#
# LabOnDemand API image.
#
# Stages:
#   base    - Python runtime + application dependencies (shared, cached layer)
#   test    - base + test dependencies + backend sources; runs the pytest suite
#   runtime - production image (default target, last stage): baked code, non-root user
#
# Build behind a proxy with: docker build --build-arg HTTP_PROXY=... --build-arg HTTPS_PROXY=... .

FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first: this layer is reused as long as requirements.txt is unchanged.
COPY requirements.txt .
RUN pip install -r requirements.txt


FROM base AS test

COPY backend/requirements-test.txt /tmp/requirements-test.txt
RUN pip install -r /tmp/requirements-test.txt

COPY backend/ /app/backend/
WORKDIR /app/backend

# The suite mocks Redis/Kubernetes and uses in-memory SQLite (see backend/tests/conftest.py):
# no .env, kubeconfig, MariaDB or Redis is needed.
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]


FROM base AS runtime

# Unprivileged user. The kubeconfig is mounted read-only at $KUBECONFIG (the Kubernetes
# client reads that variable), and /app/logs must be writable by APP_UID on bind mounts.
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --system --gid "${APP_GID}" app \
    && useradd --system --uid "${APP_UID}" --gid app --home-dir /home/app --create-home app \
    && mkdir -p /app/logs \
    && chown app:app /app/logs

ENV KUBECONFIG=/etc/labondemand/kubeconfig

COPY backend/ /app/backend/

USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/status', timeout=4).status == 200 else 1)"]

# Single worker on purpose: the API runs an in-process cleanup loop and an in-memory
# rate limiter; concurrency comes from the threadpool used by sync route handlers.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
