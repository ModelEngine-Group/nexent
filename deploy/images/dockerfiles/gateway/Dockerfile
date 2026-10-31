FROM python:3.11-slim
ARG MIRROR
WORKDIR /opt/backend
COPY deploy/images/dockerfiles/gateway/requirements.txt /tmp/gateway-requirements.txt
RUN if [ -n "$MIRROR" ]; then \
      pip install --no-cache-dir --index-url "$MIRROR" -r /tmp/gateway-requirements.txt; \
    else \
      pip install --no-cache-dir -r /tmp/gateway-requirements.txt; \
    fi
# Only copy the independent edge and its configuration dependencies.
COPY backend/gateway/__init__.py backend/gateway/edge.py backend/gateway/routing.py ./gateway/
COPY backend/gateway/authentication/__init__.py backend/gateway/authentication/credentials.py ./gateway/authentication/
COPY backend/contracts/__init__.py backend/contracts/configuration.py ./contracts/
COPY backend/contracts/authentication_routes.py ./contracts/
COPY backend/contracts/constants/__init__.py backend/contracts/constants/environment.py backend/contracts/constants/constants.py ./contracts/constants/
COPY backend/infrastructure/__init__.py ./infrastructure/
COPY backend/infrastructure/security/__init__.py backend/infrastructure/security/gateway_identity.py ./infrastructure/security/
ENV GATEWAY_AUTH_ENABLED=true
USER 65532:65532
EXPOSE 5016
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5016/health/ready', timeout=3)"
CMD ["uvicorn", "gateway.edge:app", "--host", "0.0.0.0", "--port", "5016", "--no-proxy-headers"]
