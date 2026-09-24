# Build context is the repository's test/ directory (see compose.ext-knowledge.yaml),
# because the service also embeds the existing AIDP management mock from
# test/ext_components/aidp/mock_servers/ without copying or modifying it.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Versions are pinned inline (locked resolved versions, wheels only) to keep
# the image reproducible; keep requirements.txt in sync when bumping.
RUN pip install --no-cache-dir --only-binary :all: \
    fastapi==0.139.0 \
    uvicorn==0.51.0 \
    python-multipart==0.0.32

COPY mock-services/ext-knowledge-mock/ /app/mock/
COPY ext_components/aidp/mock_servers/ /app/aidp_mock_servers/

# Point the service at the in-image copy of the AIDP mock (its repo-relative
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
