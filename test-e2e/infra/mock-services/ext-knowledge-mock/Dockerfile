# Build context is the packed, batch-owned directory produced by
# build_context.py (mock source + the AIDP mock copied from the SAME
# checkout). The repository root cannot serve as the context: its
# .dockerignore excludes test/, and the AIDP mock must come from the
# current worktree, never from a stale snapshot.
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /usr/local/bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Versions are pinned inline (locked resolved versions, wheels only) to keep
# the image reproducible; keep requirements.txt in sync when bumping.
RUN uv pip install --system --no-cache --only-binary :all: \
    fastapi==0.139.0 \
    uvicorn==0.51.0 \
    python-multipart==0.0.32 \
    httpx==0.28.1

COPY mock/ /app/mock/
COPY aidp_mock_servers/ /app/aidp_mock_servers/

# Point the service at the in-image copy of the AIDP mock (the repository
# default path does not exist inside the container).
ENV EXT_KNOWLEDGE_AIDP_MOCK_PATH=/app/aidp_mock_servers/aidp_mgmt_mock_server.py

# Runtime state (_state/) is written under /app, so hand ownership to an
# unprivileged user before switching.
RUN useradd --create-home --uid 10001 mockuser && chown -R mockuser:mockuser /app
USER mockuser

WORKDIR /app/mock
EXPOSE 30090

# Single worker on purpose: all mock state lives in this process.
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "30090"]
