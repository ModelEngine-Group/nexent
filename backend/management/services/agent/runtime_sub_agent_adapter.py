"""Unified adapters for platform-owned, specialized runtime Agents."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from nexent.core.agents.agent_model import AgentRunInfo

from consts.exceptions import RuntimeSubAgentError
from consts.model import NL2AgentRunRequest, NL2SkillRunRequest
from permissions.rbac import has_permission
from services.agent_draft_permission_service import require_agent_draft_edit

NL2SKILL_ADAPTER_KEY = "builtin:nl2skill"
NL2AGENT_ADAPTER_KEY = "builtin:nl2agent"


def _validate_run_minio_files(minio_files, user_id: str, tenant_id: str) -> None:
    """Load the canonical attachment policy lazily to avoid import cycles."""
    from agents.create_agent_info import (
        _validate_run_minio_files as validate_run_minio_files,
    )

    validate_run_minio_files(minio_files, user_id, tenant_id)


async def _build_nl2skill_run_info(**kwargs) -> AgentRunInfo:
    """Load the NL2Skill builder only after adapter authorization succeeds."""
    from services.nl2skill_service import build_nl2skill_run_info

    return await build_nl2skill_run_info(**kwargs)


def _create_nl2skill_stream(**kwargs) -> AsyncIterator[str]:
    """Load the existing NL2Skill stream factory at the runtime boundary."""
    from services.nl2skill_service import create_nl2skill_stream

    return create_nl2skill_stream(**kwargs)


async def _build_nl2agent_run_info(**kwargs) -> AgentRunInfo:
    """Load the NL2Agent builder only after adapter authorization succeeds."""
    from services.nl2agent_service import build_nl2agent_run_info

    return await build_nl2agent_run_info(**kwargs)


def _create_nl2agent_stream(**kwargs) -> AsyncIterator[str]:
    """Load the existing NL2Agent stream factory at the runtime boundary."""
    from services.nl2agent_service import create_nl2agent_stream

    return create_nl2agent_stream(**kwargs)


def _collect_request_files(
    request: NL2SkillRunRequest | NL2AgentRunRequest,
) -> list[dict] | None:
    """Collect current and historical attachment references for authorization."""
    files = [
        item for item in (request.minio_files or []) if isinstance(item, dict)
    ]
    for history_item in request.history or []:
        files.extend(
            item
            for item in (history_item.minio_files or [])
            if isinstance(item, dict)
        )
    return files or None


@dataclass(frozen=True)
class RuntimeSubAgentContext:
    """Request-scoped inputs shared by specialized runtime adapters."""

    request: NL2SkillRunRequest | NL2AgentRunRequest
    tenant_id: str
    user_id: str
    user_role: str
    language: str
    authorization: str | None = None


class RuntimeSubAgentAdapter(Protocol):
    """Contract implemented by a platform-owned specialized Agent runtime."""

    key: str

    async def authorize(self, context: RuntimeSubAgentContext) -> None: ...

    async def build_run_info(
        self,
        context: RuntimeSubAgentContext,
    ) -> AgentRunInfo: ...

    async def stream(
        self,
        context: RuntimeSubAgentContext,
    ) -> AsyncIterator[str]: ...


def _validate_context(context: RuntimeSubAgentContext, request_type: type) -> None:
    if not context.tenant_id or not context.tenant_id.strip():
        raise RuntimeSubAgentError("runtime_context_invalid")
    if not context.user_id or not context.user_id.strip():
        raise RuntimeSubAgentError("runtime_context_invalid")
    if not isinstance(context.request, request_type):
        raise RuntimeSubAgentError(
            "runtime_adapter_request_mismatch",
            message=(
                f"Adapter requires {request_type.__name__}, "
                f"got {type(context.request).__name__}"
            ),
        )


def _authorize_creation(
    context: RuntimeSubAgentContext,
    *,
    permission: str,
) -> None:
    if not has_permission(context.user_role, permission):
        raise RuntimeSubAgentError("creation_forbidden")
    try:
        _validate_run_minio_files(
            _collect_request_files(context.request),
            context.user_id,
            context.tenant_id,
        )
    except Exception as exc:
        raise RuntimeSubAgentError("attachment_forbidden") from exc


class Nl2SkillRuntimeAdapter:
    """Preserve the NL2Skill classifier and structured file event stream."""

    key = NL2SKILL_ADAPTER_KEY

    async def authorize(self, context: RuntimeSubAgentContext) -> None:
        _validate_context(context, NL2SkillRunRequest)
        _authorize_creation(context, permission="skill:create")

    async def build_run_info(
        self,
        context: RuntimeSubAgentContext,
    ) -> AgentRunInfo:
        await self.authorize(context)
        return await _build_nl2skill_run_info(
            request=context.request,
            tenant_id=context.tenant_id,
            language=context.language,
        )

    async def stream(
        self,
        context: RuntimeSubAgentContext,
    ) -> AsyncIterator[str]:
        await self.authorize(context)
        return _create_nl2skill_stream(
            request=context.request,
            tenant_id=context.tenant_id,
            language=context.language,
        )


class Nl2AgentRuntimeAdapter:
    """Preserve NL2Agent draft authorization, cards, and boundary observer."""

    key = NL2AGENT_ADAPTER_KEY

    async def authorize(self, context: RuntimeSubAgentContext) -> None:
        _validate_context(context, NL2AgentRunRequest)
        _authorize_creation(context, permission="agent:create")
        try:
            require_agent_draft_edit(
                agent_id=context.request.agent_id,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as exc:
            raise RuntimeSubAgentError("draft_forbidden") from exc

    async def build_run_info(
        self,
        context: RuntimeSubAgentContext,
    ) -> AgentRunInfo:
        await self.authorize(context)
        return await _build_nl2agent_run_info(
            request=context.request,
            tenant_id=context.tenant_id,
            language=context.language,
            authorization=context.authorization,
        )

    async def stream(
        self,
        context: RuntimeSubAgentContext,
    ) -> AsyncIterator[str]:
        await self.authorize(context)
        return _create_nl2agent_stream(
            request=context.request,
            tenant_id=context.tenant_id,
            language=context.language,
            authorization=context.authorization,
        )


_ADAPTERS: dict[str, RuntimeSubAgentAdapter] = {
    NL2SKILL_ADAPTER_KEY: Nl2SkillRuntimeAdapter(),
    NL2AGENT_ADAPTER_KEY: Nl2AgentRuntimeAdapter(),
}


def get_runtime_sub_agent_adapter(key: str) -> RuntimeSubAgentAdapter:
    """Resolve a registered specialized runtime by its stable key."""
    try:
        return _ADAPTERS[key]
    except KeyError as exc:
        raise RuntimeSubAgentError(
            "runtime_adapter_not_found",
            message=f"Unknown runtime sub-Agent adapter: {key}",
        ) from exc


def list_runtime_sub_agent_adapters() -> list[str]:
    """Return stable adapter keys for diagnostics and Workbench discovery."""
    return sorted(_ADAPTERS)
