FROM python:3.11-slim
WORKDIR /opt/backend
COPY deploy/images/dockerfiles/gateway/requirements.txt /tmp/gateway-requirements.txt
RUN pip install --no-cache-dir -r /tmp/gateway-requirements.txt
# Only copy the independent edge and its configuration dependencies.
COPY backend/gateway/__init__.py backend/gateway/edge.py backend/gateway/routing.py ./gateway/
COPY backend/contracts/__init__.py backend/contracts/configuration.py ./contracts/
COPY backend/contracts/constants/__init__.py backend/contracts/constants/environment.py ./contracts/constants/
USER 65532:65532
EXPOSE 5016
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5016/health/ready', timeout=3)"
CMD ["uvicorn", "gateway.edge:app", "--host", "0.0.0.0", "--port", "5016", "--no-proxy-headers"]
