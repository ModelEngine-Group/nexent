FROM python:3.10-slim

ARG MIRROR
ARG APT_MIRROR

# Set correct permissions as root
USER root
RUN umask 0022

# Configure apt sources based on build argument
RUN if [ "$APT_MIRROR" = "tsinghua" ]; then \
        rm -f /etc/apt/sources.list.d/* && \
        echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
        echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
        echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-backports main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
        echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian-security bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list; \
    fi && \
    apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg xz-utils && \
    rm -rf /var/lib/apt/lists/*

# Optional pip mirror for Python packages
RUN if [ -n "$MIRROR" ]; then pip config set global.index-url "$MIRROR"; fi

# Install uv (fast Python package installer)
RUN pip install --no-cache-dir uv

ARG MCP_PROXY_VERSION

WORKDIR /opt

# Install mcp-proxy from PyPI (optionally pinned)
RUN if [ -n "$MCP_PROXY_VERSION" ]; then \
        pip install --no-cache-dir "mcp-proxy==$MCP_PROXY_VERSION"; \
    else \
        pip install --no-cache-dir mcp-proxy; \
    fi

# Install Node.js 20 from official binaries (pin exact version to avoid repo issues)
ARG NODE_VERSION=20.17.0
RUN set -euo pipefail && \
    arch="$(dpkg --print-architecture)" && \
    case "${arch}" in \
        amd64) node_arch="x64" ;; \
        arm64) node_arch="arm64" ;; \
        *) echo "Unsupported architecture: ${arch}" >&2; exit 1 ;; \
    esac && \
    curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" && \
    tar -C /usr/local --strip-components=1 -xJf "node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" && \
    rm "node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" && \
    node -v && npm -v