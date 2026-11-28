# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

FROM python:3.11-slim AS base
ARG MIRROR
ARG APT_MIRROR
ARG TARGETARCH
LABEL authors="nexent"
ENV TZ=Asia/Shanghai

# Set correct permissions as root
USER root
RUN umask 0022

# Configure apt sources based on build argument
RUN --mount=type=cache,id=nexent-main-apt-cache-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=nexent-main-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
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
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        curl tzdata

FROM base AS litellm-models
ARG MODELS_DEV_CATALOG_URL=https://models.dev/catalog.json

# Bundle reasoning capabilities independently of application code changes.
RUN curl -fsSL --proto '=https' -o /models_dev_catalog.json "$MODELS_DEV_CATALOG_URL"

# Bundle the LiteLLM catalog for offline capacity lookup.
RUN curl -fsSL --proto '=https' -o /litellm_models.json \
    https://cdn.jsdelivr.net/gh/BerriAI/litellm@main/model_prices_and_context_window.json \
    || echo '{}' > /litellm_models.json

FROM base AS builder
ARG MIRROR
ARG TARGETARCH
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /usr/local/bin/
WORKDIR /opt/backend

# Layer 0: install base dependencies. backend extras reference the local sdk
# via [tool.uv.sources], so the sdk must exist before uv sync resolves.
COPY backend/pyproject.toml /opt/backend/pyproject.toml
COPY sdk/pyproject.toml /opt/sdk/pyproject.toml
RUN --mount=type=cache,id=nexent-main-uv-${TARGETARCH},target=/root/.cache/uv,sharing=locked \
    uv sync --no-default-groups --link-mode copy $(test -n "$MIRROR" && echo "-i $MIRROR") && \
    uv export --locked --only-group management --no-emit-project --no-hashes \
        $(test -n "$MIRROR" && echo "-i $MIRROR") \
        -o /opt/backend/management-requirements.txt
RUN mkdir -p "$TIKTOKEN_CACHE_DIR" && \
    /opt/backend/.venv/bin/python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
# Layer 1: reinstall the sdk with its performance extra (non-editable)
COPY sdk /opt/sdk
RUN --mount=type=cache,id=nexent-main-uv-${TARGETARCH},target=/root/.cache/uv,sharing=locked \
    uv pip install --link-mode copy "/opt/sdk[performance]" $(test -n "$MIRROR" && echo "-i $MIRROR")

FROM base AS backend-common

ENV VIRTUAL_ENV=/opt/backend/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache
WORKDIR /opt/backend

COPY --from=builder /opt/backend/.venv /opt/backend/.venv
COPY --from=builder /opt/tiktoken-cache /opt/tiktoken-cache
COPY --from=litellm-models /litellm_models.json /opt/nexent/litellm_models.json
COPY infrastructure /opt/infrastructure
ENV PYTHONPATH=/opt:/opt/backend
COPY --from=litellm-models /models_dev_catalog.json /opt/backend/configs/models_dev_catalog.json
COPY VERSION /opt/nexent/VERSION
RUN /opt/backend/.venv/bin/python -B -c "from nexent.core.model_service.profiles.resolver import load_profile_catalog; load_profile_catalog()"
COPY deploy/common/run-sql-migrations.sh deploy/common/start-backend.sh /opt/nexent/scripts/
RUN chmod +x /opt/nexent/scripts/*.sh
RUN --mount=type=cache,id=nexent-main-apt-cache-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=nexent-main-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bind9-dnsutils btop file iproute2 jq less lsof nano netcat-openbsd \
        postgresql-client procps psmisc redis-tools strace tcpdump

# Create SSH key directory for Terminal tool
RUN mkdir -p /opt/ssh-keys

WORKDIR /opt

FROM backend-common AS management-base
ARG TARGETARCH
ARG MIRROR
RUN --mount=type=cache,id=nexent-main-apt-cache-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=nexent-main-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        fontconfig fonts-noto-cjk unzip && \
    fc-cache -f
RUN --mount=type=bind,from=builder,source=/usr/local/bin/uv,target=/tmp/uv \
    --mount=type=bind,from=builder,source=/opt/backend/management-requirements.txt,target=/tmp/management-requirements.txt \
    --mount=type=cache,id=nexent-main-uv-${TARGETARCH},target=/root/.cache/uv,sharing=locked \
    /tmp/uv pip install --link-mode copy -r /tmp/management-requirements.txt \
        $(test -n "$MIRROR" && echo "-i $MIRROR")

FROM management-base AS management

ENV NEXENT_SQL_STARTUP_MODE=migrate
COPY deploy/sql/tools/supabase_to_postgres /opt/deploy/sql/tools/supabase_to_postgres
COPY deploy/sql/migrations/v2.9.0_merged_migrations.sql /opt/deploy/sql/migrations/v2.9.0_merged_migrations.sql
COPY deploy/common/run-sql-migrations.sh /opt/nexent/scripts/
RUN chmod +x /opt/nexent/scripts/run-sql-migrations.sh

COPY backend/__init__.py /opt/backend/
COPY backend/management /opt/backend/management
COPY backend/contracts /opt/backend/contracts
COPY backend/configs /opt/backend/configs
COPY backend/permissions /opt/backend/permissions
COPY backend/ext_components /opt/backend/ext_components
COPY backend/adapters /opt/backend/adapters
COPY backend/assets/baidu_stopwords.txt /opt/backend/assets/
COPY backend/memory_provider_plugins /opt/backend/memory_provider_plugins
COPY backend/tool_collection/langchain /opt/backend/tool_collection/langchain
COPY backend/services/__init__.py \
    backend/services/nl2agent_configuration.py \
    backend/services/nl2agent_knowledge_recommendations.py \
    backend/services/nl2agent_prompt_service.py \
    backend/services/nl2agent_resource_flow.py \
    backend/services/nl2agent_retrieval_progress.py \
    backend/services/nl2agent_semantic_retrieval.py \
    backend/services/nl2agent_state_service.py /opt/backend/services/
COPY backend/tool_collection/mcp /opt/backend/tool_collection/mcp
COPY backend/mcp /opt/backend/mcp
COPY backend/http/client.py backend/http/logging.py backend/http/mcp_service.py /opt/backend/http/
RUN ln -s ../management/launcher.py /opt/backend/http/config_service.py
COPY backend/http/server /opt/backend/http/server
COPY backend/gateway/__init__.py /opt/backend/gateway/
COPY backend/gateway/identity /opt/backend/gateway/identity

# Runtime target excludes Management business code.
FROM backend-common AS runtime

RUN --mount=type=cache,id=nexent-main-apt-cache-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=nexent-main-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends sysstat

ENV NEXENT_SQL_STARTUP_MODE=off

COPY backend/__init__.py /opt/backend/
COPY backend/runtime /opt/backend/runtime
COPY backend/tool_collection/langchain /opt/backend/tool_collection/langchain
COPY backend/contracts /opt/backend/contracts
COPY backend/configs /opt/backend/configs
COPY backend/assets/baidu_stopwords.txt /opt/backend/assets/
COPY backend/permissions/__init__.py backend/permissions/dac.py backend/permissions/models.py /opt/backend/permissions/
COPY backend/ext_components/__init__.py /opt/backend/ext_components/
COPY backend/ext_components/aidp/__init__.py /opt/backend/ext_components/aidp/
COPY backend/ext_components/aidp/consts /opt/backend/ext_components/aidp/consts
COPY backend/ext_components/aidp/database /opt/backend/ext_components/aidp/database
COPY backend/ext_components/aidp/services/__init__.py \
    backend/ext_components/aidp/services/aidp_access_service.py \
    backend/ext_components/aidp/services/aidp_permission_service.py \
    backend/ext_components/aidp/services/aidp_service.py /opt/backend/ext_components/aidp/services/
COPY backend/http/client.py backend/http/logging.py /opt/backend/http/
RUN ln -s ../runtime/launcher.py /opt/backend/http/runtime_service.py
COPY backend/http/server /opt/backend/http/server
COPY backend/gateway/__init__.py /opt/backend/gateway/
COPY backend/gateway/identity /opt/backend/gateway/identity
