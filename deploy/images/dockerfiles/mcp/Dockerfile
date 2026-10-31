FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /usr/local/bin/

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
        for apt_source in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources /etc/apt/sources.list.d/*.list; do \
            [ -f "$apt_source" ] || continue; \
            sed -i \
                -e 's|https\?://deb.debian.org/debian-security|http://security.debian.org/debian-security|g' \
                -e 's|https\?://security.debian.org/debian-security|http://security.debian.org/debian-security|g' \
                -e 's|https\?://deb.debian.org/debian|http://mirrors.tuna.tsinghua.edu.cn/debian|g' \
                "$apt_source"; \
        done; \
    fi && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        vim \
        procps \
        wget \
        less \
        ca-certificates \
        gnupg \
        xz-utils

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

# Optional package mirror is passed directly to uv.

ARG MCP_PROXY_VERSION

WORKDIR /opt

# Install mcp-proxy from PyPI (optionally pinned)
RUN --mount=type=cache,id=nexent-mcp-uv-${TARGETARCH},target=/root/.cache/uv,sharing=locked \
    if [ -n "$MCP_PROXY_VERSION" ]; then \
        uv pip install --system --link-mode copy "mcp-proxy==$MCP_PROXY_VERSION" $(test -n "$MIRROR" && echo "--default-index $MIRROR"); \
    else \
        uv pip install --system --link-mode copy mcp-proxy $(test -n "$MIRROR" && echo "--default-index $MIRROR"); \
    fi
