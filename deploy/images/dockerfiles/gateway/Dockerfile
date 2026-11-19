FROM python:3.11-slim
ARG MIRROR
WORKDIR /opt
COPY backend/gateway/requirements.txt /tmp/gateway-requirements.txt
RUN if [ -n "$MIRROR" ]; then \
      pip install --no-cache-dir --index-url "$MIRROR" -r /tmp/gateway-requirements.txt; \
    else \
      pip install --no-cache-dir -r /tmp/gateway-requirements.txt; \
    fi
COPY backend/gateway/*.py /opt/backend/gateway/
COPY backend/gateway/exposure/ /opt/backend/gateway/exposure/
COPY backend/gateway/proxy/ /opt/backend/gateway/proxy/
COPY backend/gateway/security/ /opt/backend/gateway/security/
COPY backend/gateway/mcp/ /opt/backend/gateway/mcp/
COPY infrastructure/__init__.py /opt/infrastructure/__init__.py
COPY infrastructure/rdb/__init__.py infrastructure/rdb/identity.py /opt/infrastructure/rdb/
COPY backend/__init__.py /opt/backend/__init__.py
COPY backend/http/gateway_service.py /opt/backend/http/gateway_service.py
ENV PYTHONPATH=/opt:/opt/backend
USER 65532:65532
EXPOSE 5013
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -m gateway.healthcheck
