FROM python:3.11-slim
ARG MIRROR
WORKDIR /opt
COPY backend/gateway/requirements.txt /tmp/gateway-requirements.txt
RUN if [ -n "$MIRROR" ]; then \
      pip install --no-cache-dir --index-url "$MIRROR" -r /tmp/gateway-requirements.txt; \
    else \
      pip install --no-cache-dir -r /tmp/gateway-requirements.txt; \
    fi
COPY backend/gateway/ /opt/backend/gateway/
COPY backend/infrastructure/__init__.py /opt/backend/infrastructure/__init__.py
COPY backend/infrastructure/database/__init__.py backend/infrastructure/database/identity.py /opt/backend/infrastructure/database/
COPY backend/infrastructure/security/ /opt/backend/infrastructure/security/
COPY backend/gateway_service.py /opt/backend/gateway_service.py
ENV PYTHONPATH=/opt/backend
USER 65532:65532
EXPOSE 5013
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -m gateway.healthcheck
