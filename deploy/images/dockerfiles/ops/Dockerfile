# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

FROM ghcr.io/astral-sh/uv:0.13.6 AS uv
FROM python:3.11-slim

ARG MIRROR
ARG TARGETARCH
ENV VIRTUAL_ENV=/opt/backend/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV PYTHONPATH=/opt:/opt/backend
ENV NEXENT_SQL_STARTUP_MODE=off
ENV PYTHON_DOTENV_DISABLED=1
ENV TZ=Asia/Shanghai
WORKDIR /opt

RUN --mount=type=bind,from=uv,source=/uv,target=/usr/local/bin/uv \
    --mount=type=bind,source=backend/pyproject.toml,target=/tmp/pyproject.toml \
    --mount=type=cache,id=nexent-ops-uv-${TARGETARCH},target=/root/.cache/uv \
    uv venv "$VIRTUAL_ENV" && \
    uv --no-config pip install --strict --link-mode copy --python "$VIRTUAL_ENV/bin/python" \
        ${MIRROR:+--default-index "$MIRROR"} --group /tmp/pyproject.toml:ops

RUN --mount=type=cache,id=nexent-ops-apt-cache-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=nexent-ops-apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends postgresql-client

COPY backend/contracts /opt/backend/contracts
COPY backend/gateway/identity /opt/backend/gateway/identity
COPY backend/ops /opt/backend/ops
COPY backend/permissions /opt/backend/permissions
COPY infrastructure/monitoring /opt/infrastructure/monitoring
COPY infrastructure/system_configuration /opt/infrastructure/system_configuration
COPY backend/__init__.py /opt/backend/
COPY backend/ext_components/__init__.py /opt/backend/ext_components/
COPY backend/ext_components/aidp/__init__.py /opt/backend/ext_components/aidp/
COPY backend/ext_components/aidp/consts/aidp_exceptions.py /opt/backend/ext_components/aidp/consts/
COPY backend/gateway/__init__.py /opt/backend/gateway/
COPY backend/http/logging.py backend/http/ops_service.py /opt/backend/http/
COPY backend/http/server/__init__.py backend/http/server/exception_handlers.py /opt/backend/http/server/
COPY backend/management/__init__.py /opt/backend/management/
COPY backend/management/api/__init__.py /opt/backend/management/api/
COPY backend/management/api/permission /opt/backend/management/api/permission
COPY backend/management/db/__init__.py backend/management/db/base.py /opt/backend/management/db/
COPY backend/management/db/agent/__init__.py backend/management/db/agent/models.py /opt/backend/management/db/agent/
COPY \
    backend/management/db/automation/__init__.py \
    backend/management/db/automation/models.py \
    /opt/backend/management/db/automation/
COPY \
    backend/management/db/configuration/__init__.py \
    backend/management/db/configuration/models.py \
    /opt/backend/management/db/configuration/
COPY \
    backend/management/db/conversation/__init__.py \
    backend/management/db/conversation/branch_titles.py \
    backend/management/db/conversation/classification.py \
    backend/management/db/conversation/memory_completion.py \
    backend/management/db/conversation/models.py \
    backend/management/db/conversation/projection_receipt.py \
    backend/management/db/conversation/repository.py \
    /opt/backend/management/db/conversation/
COPY \
    backend/management/db/identity/__init__.py \
    backend/management/db/identity/account.py \
    backend/management/db/identity/cas_session.py \
    backend/management/db/identity/conversation_agent_history_db.py \
    backend/management/db/identity/membership.py \
    backend/management/db/identity/models.py \
    backend/management/db/identity/role_permission.py \
    backend/management/db/identity/roles.py \
    backend/management/db/identity/token.py \
    backend/management/db/identity/user_tenant.py \
    /opt/backend/management/db/identity/
COPY \
    backend/management/db/knowledge_base/__init__.py \
    backend/management/db/knowledge_base/models.py \
    /opt/backend/management/db/knowledge_base/
COPY backend/management/db/mcp/__init__.py backend/management/db/mcp/models.py /opt/backend/management/db/mcp/
COPY backend/management/db/model/__init__.py backend/management/db/model/models.py /opt/backend/management/db/model/
COPY backend/management/services/__init__.py /opt/backend/management/services/
COPY \
    backend/management/services/permission/__init__.py \
    backend/management/services/permission/ops_access.py \
    /opt/backend/management/services/permission/
COPY \
    backend/management/services/permission/identity/__init__.py \
    backend/management/services/permission/identity/credentials.py \
    backend/management/services/permission/identity/northbound.py \
    backend/management/services/permission/identity/session.py \
    backend/management/services/permission/identity/signatures.py \
    /opt/backend/management/services/permission/identity/
COPY \
    backend/management/utils/__init__.py \
    backend/management/utils/account_passwords.py \
    backend/management/utils/audit_fields.py \
    backend/management/utils/request_context.py \
    backend/management/utils/serialization.py \
    /opt/backend/management/utils/
COPY infrastructure/__init__.py infrastructure/skill_execution.py /opt/infrastructure/
COPY \
    infrastructure/rdb/__init__.py \
    infrastructure/rdb/account_access.py \
    infrastructure/rdb/account_record.py \
    infrastructure/rdb/agent_admission.py \
    infrastructure/rdb/agent_execution.py \
    infrastructure/rdb/audit_fields.py \
    infrastructure/rdb/base.py \
    infrastructure/rdb/client.py \
    infrastructure/rdb/conversation_record.py \
    infrastructure/rdb/conversation_state.py \
    infrastructure/rdb/knowledge_search_records.py \
    infrastructure/rdb/mcp_execution_records.py \
    infrastructure/rdb/model_monitoring.py \
    infrastructure/rdb/model_record.py \
    infrastructure/rdb/orm.py \
    infrastructure/rdb/skill_execution_records.py \
    infrastructure/rdb/tenant_config_record.py \
    /opt/infrastructure/rdb/
COPY infrastructure/rdb/trajectory /opt/infrastructure/rdb/trajectory
COPY infrastructure/trace /opt/infrastructure/trace
COPY sdk/nexent /opt/nexent
COPY VERSION /opt/nexent/VERSION
COPY --chmod=0755 deploy/common/start-ops.sh deploy/common/run-sql-migrations.sh deploy/common/run-ops-sql-migrations.sh /opt/nexent/scripts/
# Preserve older deployed command paths with the same Ops-only initialization.
RUN ln -s start-ops.sh /opt/nexent/scripts/start-backend.sh
COPY deploy/sql/ops-init.sql /opt/nexent/ops-sql/ops-init.sql
COPY deploy/sql/migrations/ops/ /opt/nexent/ops-sql/migrations/

ENTRYPOINT ["/opt/nexent/scripts/start-ops.sh", "python", "-m", "backend.http.ops_service"]
