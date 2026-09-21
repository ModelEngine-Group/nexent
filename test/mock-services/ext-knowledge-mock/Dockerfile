# Build context is the repository's test/ directory (see compose.ext-knowledge.yaml),
# because the service also embeds the existing AIDP management mock from
# test/ext_components/aidp/mock_servers/ without copying or modifying it.
FROM python:3.11-slim

WORKDIR /app

COPY mock-services/ext-knowledge-mock/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY mock-services/ext-knowledge-mock/ /app/mock/
COPY ext_components/aidp/mock_servers/ /app/aidp_mock_servers/

# Point the service at the in-image copy of the AIDP mock (its repo-relative
# default path does not exist inside the container).
ENV EXT_KNOWLEDGE_AIDP_MOCK_PATH=/app/aidp_mock_servers/aidp_mgmt_mock_server.py

WORKDIR /app/mock
EXPOSE 30090

# Single worker on purpose: all mock state lives in this process.
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "30090"]
