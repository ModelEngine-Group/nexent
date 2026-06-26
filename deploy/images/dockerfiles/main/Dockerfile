# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS base
ARG MIRROR
ARG APT_MIRROR
ARG TARGETARCH
LABEL authors="nexent"

# Set correct permissions as root
USER root
RUN umask 0022

# Configure apt sources based on build argument
RUN --mount=type=cache,id=nexent-main-apt-cache-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=nexent-main-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    mkdir -p /var/cache/apt/archives /var/lib/apt/lists/partial && \
    if [ "$APT_MIRROR" = "tsinghua" ]; then \
        rm -f /etc/apt/sources.list.d/* && \
        echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
        echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
        echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-backports main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
        echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian-security bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list; \
    fi && \
    apt-get update && apt-get install -y --no-install-recommends curl postgresql-client

FROM base AS builder
ARG MIRROR
ARG TARGETARCH

RUN --mount=type=cache,id=nexent-main-pip-${TARGETARCH},target=/root/.cache/pip,sharing=locked \
    pip install uv $(test -n "$MIRROR" && echo "-i $MIRROR")
WORKDIR /opt/backend

# Layer 0: install base dependencies
COPY backend/pyproject.toml /opt/backend/pyproject.toml
RUN --mount=type=cache,id=nexent-main-uv-${TARGETARCH},target=/root/.cache/uv,sharing=locked \
    uv sync --link-mode copy $(test -n "$MIRROR" && echo "-i $MIRROR")
# Layer 1: install sdk in link mode
COPY sdk /opt/sdk
RUN --mount=type=cache,id=nexent-main-uv-${TARGETARCH},target=/root/.cache/uv,sharing=locked \
    uv pip install --link-mode copy "/opt/sdk[performance]" $(test -n "$MIRROR" && echo "-i $MIRROR")

FROM base AS final

ENV VIRTUAL_ENV=/opt/backend/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
WORKDIR /opt/backend

COPY --from=builder /opt/backend/.venv /opt/backend/.venv
COPY --from=builder /opt/sdk /opt/sdk

# Pre-download tiktoken cl100k_base model to avoid network issues during runtime.
RUN python -c "import tiktoken; enc = tiktoken.get_encoding('cl100k_base')"

# Layer 2: copy backend code
COPY backend /opt/backend
COPY VERSION /opt/nexent/VERSION
COPY deploy/common/run-sql-migrations.sh deploy/common/start-backend.sh /opt/nexent/scripts/
RUN chmod +x /opt/nexent/scripts/run-sql-migrations.sh /opt/nexent/scripts/start-backend.sh

# Create SSH key directory for Terminal tool
RUN mkdir -p /opt/ssh-keys
VOLUME ["/opt/ssh-keys"]

WORKDIR /opt

# Expose the service port
EXPOSE 5010
