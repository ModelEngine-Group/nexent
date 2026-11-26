FROM python:3.11-slim
ARG MIRROR
ARG APT_MIRROR
ARG TARGETARCH
WORKDIR /opt
RUN --mount=type=cache,id=nexent-gateway-apt-cache-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=nexent-gateway-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    if [ "$APT_MIRROR" = "tsinghua" ]; then \
        for apt_source in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources /etc/apt/sources.list.d/*.list; do \
            [ -f "$apt_source" ] || continue; \
            sed -i \
                -e 's|https\?://deb.debian.org/debian-security|http://security.debian.org/debian-security|g' \
                -e 's|https\?://deb.debian.org/debian|http://mirrors.tuna.tsinghua.edu.cn/debian|g' \
                "$apt_source"; \
        done; \
    fi && \
    apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bind9-dnsutils curl iproute2 jq less netcat-openbsd postgresql-client procps

COPY backend/gateway/requirements.txt /tmp/gateway-requirements.txt
RUN if [ -n "$MIRROR" ]; then \
      pip install --no-cache-dir --index-url "$MIRROR" -r /tmp/gateway-requirements.txt; \
    else \
      pip install --no-cache-dir -r /tmp/gateway-requirements.txt; \
    fi
COPY backend/gateway /opt/backend/gateway
COPY infrastructure/__init__.py /opt/infrastructure/__init__.py
COPY infrastructure/rdb/__init__.py infrastructure/rdb/identity.py /opt/infrastructure/rdb/
COPY backend/__init__.py /opt/backend/__init__.py
COPY backend/http/gateway_service.py /opt/backend/http/gateway_service.py
ENV PYTHONPATH=/opt:/opt/backend
EXPOSE 5013
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -m gateway.healthcheck
