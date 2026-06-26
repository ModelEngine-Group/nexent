# syntax=docker/dockerfile:1.7

FROM python:3.11-slim

ARG MIRROR
ARG APT_MIRROR
ARG TARGETARCH

# Set correct permissions as root
USER root
RUN umask 0022

# Configure apt sources based on build argument
RUN --mount=type=cache,id=nexent-mcp-apt-cache-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=nexent-mcp-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    mkdir -p /var/cache/apt/archives /var/lib/apt/lists/partial && \
    if [ "$APT_MIRROR" = "tsinghua" ]; then \
        rm -f /etc/apt/sources.list.d/* && \
        echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
        echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
        echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-backports main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
        echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian-security bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list; \
    fi && \
    apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg xz-utils

# Install Node.js 20 from official binaries (pin exact version to avoid repo issues)
ARG NODE_VERSION=20.17.0
RUN --mount=type=cache,id=nexent-mcp-nodejs-${TARGETARCH},target=/var/cache/nodejs,sharing=locked \
    set -eu && \
    arch="$(dpkg --print-architecture)" && \
    case "${arch}" in \
        amd64) node_arch="x64" ;; \
        arm64) node_arch="arm64" ;; \
        *) echo "Unsupported architecture: ${arch}" >&2; exit 1 ;; \
    esac && \
    node_tarball="/var/cache/nodejs/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" && \
    if [ ! -f "$node_tarball" ]; then \
        curl -fsSLo "$node_tarball" "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz"; \
    fi && \
    tar -C /usr/local --strip-components=1 -xJf "$node_tarball" && \
    node -v && npm -v

# Optional pip mirror for Python packages
RUN if [ -n "$MIRROR" ]; then pip config set global.index-url "$MIRROR"; fi

ARG MCP_PROXY_VERSION

WORKDIR /opt

# Install mcp-proxy from PyPI (optionally pinned)
RUN --mount=type=cache,id=nexent-mcp-pip-${TARGETARCH},target=/root/.cache/pip,sharing=locked \
    if [ -n "$MCP_PROXY_VERSION" ]; then \
        pip install "mcp-proxy==$MCP_PROXY_VERSION"; \
    else \
        pip install mcp-proxy; \
    fi
