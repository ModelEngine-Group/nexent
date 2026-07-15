"""Lazy OpenJiuwen 0.1.15 compatibility helpers without import hooks."""

from __future__ import annotations

import logging
import ssl
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata
from typing import Any, Mapping

from packaging.version import Version


OPENJIUWEN_MIN_VERSION = Version("0.1.15")
OPENJIUWEN_MAX_VERSION = Version("0.1.16")
AGENT_SANDBOX_MIN_VERSION = Version("0.0.26")
NEXENT_OPENAI_CLIENT_PROVIDER = "NexentOpenAI"


logger = logging.getLogger(__name__)


class OpenJiuwenCompatibilityError(RuntimeError):
    """Raised when the selected OpenJiuwen installation is incompatible."""


@dataclass(frozen=True)
class OpenJiuwenPublicAPI:
    """Public OpenJiuwen objects shared by runtime and prompt optimization."""

    AgentCard: Any
    ReActAgentConfig: Any
    ReActAgent: Any
    ModelRequestConfig: Any
    ModelClientConfig: Any
    McpServerConfig: Any
    ToolCard: Any
    LocalFunction: Any
    ContextEngineConfig: Any
    ContextEngine: Any
    Runner: Any
    create_agent_session: Any
    UserMessage: Any
    AssistantMessage: Any
    SystemMessage: Any
    ToolMessage: Any
    NexentOpenAIModelClient: Any


@dataclass(frozen=True)
class OpenJiuwenSandboxAPI:
    """Public OpenJiuwen sandbox objects loaded only when sandbox is enabled."""

    SysOperationCard: Any
    OperationMode: Any
    SandboxGatewayConfig: Any
    SandboxIsolationConfig: Any
    PreDeployLauncherConfig: Any
    ContainerScope: Any
    SandboxRegistry: Any
    Runner: Any


@lru_cache(maxsize=1)
def load_openjiuwen_public_api() -> OpenJiuwenPublicAPI:
    """Validate and load only the public APIs required by Nexent."""
    installed = validate_openjiuwen_version()
    try:
        from openjiuwen.core.context_engine import ContextEngine, ContextEngineConfig
        from openjiuwen.core.foundation.llm import (
            AssistantMessage,
            ModelClientConfig,
            ModelRequestConfig,
            OpenAIModelClient,
            SystemMessage,
            ToolMessage,
            UserMessage,
        )
        from openjiuwen.core.foundation.tool import LocalFunction, ToolCard
        from openjiuwen.core.foundation.tool.mcp.base import McpServerConfig
        from openjiuwen.core.runner import Runner
        from openjiuwen.core.single_agent import (
            AgentCard,
            ReActAgent,
            ReActAgentConfig,
            create_agent_session,
        )
    except ImportError as exc:
        raise OpenJiuwenCompatibilityError(
            "OpenJiuwen 0.1.15 public runtime APIs are unavailable."
        ) from exc

    _validate_public_runtime_contract(
        ReActAgentConfig=ReActAgentConfig,
        ContextEngine=ContextEngine,
        Runner=Runner,
        create_agent_session=create_agent_session,
    )
    logger.info(
        "OpenJiuwen SDK public API validated, version=%s, client_provider=%s",
        installed,
        NEXENT_OPENAI_CLIENT_PROVIDER,
    )

    class NexentOpenAIModelClient(OpenAIModelClient):
        """OpenAI-compatible client with Nexent TLS and message semantics."""

        __client_name__ = [NEXENT_OPENAI_CLIENT_PROVIDER]

        def _validate_config(self) -> None:
            if not self.model_client_config.api_key:
                raise ValueError("model client config api_key is required")
            if not self.model_client_config.api_base:
                raise ValueError("model client config api_base is required")
            if not isinstance(self.model_client_config.verify_ssl, bool):
                raise ValueError("model client config verify_ssl must be boolean")

        @staticmethod
        def _convert_messages_to_dict(messages: Any) -> list[dict[str, Any]]:
            converted = OpenAIModelClient._convert_messages_to_dict(messages)
            return [
                {**message, "content": flatten_message_content(message.get("content"))}
                for message in converted
            ]

        def _create_async_openai_client(self, timeout: float | None = None) -> Any:
            import httpx
            from openai import AsyncOpenAI
            from openjiuwen.core.common.security.url_utils import UrlUtils

            verify_ssl = self.model_client_config.verify_ssl
            ssl_cert = self.model_client_config.ssl_cert
            if verify_ssl:
                verify: bool | ssl.SSLContext = ssl.create_default_context(
                    cafile=ssl_cert
                )
            else:
                verify = False
            http_client = httpx.AsyncClient(
                proxy=UrlUtils.get_global_proxy_url(self.model_client_config.api_base),
                verify=verify,
            )
            return AsyncOpenAI(
                api_key=self.model_client_config.api_key,
                base_url=self.model_client_config.api_base,
                http_client=http_client,
                timeout=timeout or self.model_client_config.timeout,
                max_retries=self.model_client_config.max_retries,
            )

    return OpenJiuwenPublicAPI(
        AgentCard=AgentCard,
        ReActAgentConfig=ReActAgentConfig,
        ReActAgent=ReActAgent,
        ModelRequestConfig=ModelRequestConfig,
        ModelClientConfig=ModelClientConfig,
        McpServerConfig=McpServerConfig,
        ToolCard=ToolCard,
        LocalFunction=LocalFunction,
        ContextEngineConfig=ContextEngineConfig,
        ContextEngine=ContextEngine,
        Runner=Runner,
        create_agent_session=create_agent_session,
        UserMessage=UserMessage,
        AssistantMessage=AssistantMessage,
        SystemMessage=SystemMessage,
        ToolMessage=ToolMessage,
        NexentOpenAIModelClient=NexentOpenAIModelClient,
    )


def validate_openjiuwen_version() -> Version:
    """Validate the supported OpenJiuwen distribution range."""
    try:
        installed = Version(metadata.version("openjiuwen"))
    except metadata.PackageNotFoundError as exc:
        raise OpenJiuwenCompatibilityError("OpenJiuwen is not installed.") from exc
    if not OPENJIUWEN_MIN_VERSION <= installed < OPENJIUWEN_MAX_VERSION:
        raise OpenJiuwenCompatibilityError(
            f"OpenJiuwen version must satisfy >=0.1.15,<0.1.16; found {installed}."
        )
    return installed


@lru_cache(maxsize=1)
def load_openjiuwen_sandbox_api() -> OpenJiuwenSandboxAPI:
    """Validate and load the fixed AIO sandbox contract."""
    validate_openjiuwen_version()
    try:
        agent_sandbox_version = Version(metadata.version("agent-sandbox"))
    except metadata.PackageNotFoundError as exc:
        raise OpenJiuwenCompatibilityError(
            "OpenJiuwen sandbox requires agent-sandbox>=0.0.26."
        ) from exc
    if agent_sandbox_version < AGENT_SANDBOX_MIN_VERSION:
        raise OpenJiuwenCompatibilityError(
            "OpenJiuwen sandbox requires agent-sandbox>=0.0.26; "
            f"found {agent_sandbox_version}."
        )

    try:
        import openjiuwen.extensions.sys_operation.sandbox  # noqa: F401
        from openjiuwen.core.runner import Runner
        from openjiuwen.core.sys_operation import SysOperationCard
        from openjiuwen.core.sys_operation.base import OperationMode
        from openjiuwen.core.sys_operation.config import (
            ContainerScope,
            PreDeployLauncherConfig,
            SandboxGatewayConfig,
            SandboxIsolationConfig,
        )
        from openjiuwen.core.sys_operation.sandbox.sandbox_registry import (
            SandboxRegistry,
        )
    except ImportError as exc:
        raise OpenJiuwenCompatibilityError(
            "OpenJiuwen 0.1.15 public sandbox APIs are unavailable."
        ) from exc

    missing: list[str] = []
    resource_mgr = getattr(Runner, "resource_mgr", None)
    for method_name in {
        "add_sys_operation",
        "get_sys_operation",
        "get_sys_op_tool_cards",
        "remove_sys_operation",
    }:
        if not callable(getattr(resource_mgr, method_name, None)):
            missing.append(f"Runner.resource_mgr.{method_name}")
    for operation_type in ("fs", "shell", "code"):
        if SandboxRegistry.get_provider_cls("aio", operation_type) is None:
            missing.append(f"SandboxRegistry.aio.{operation_type}")
    if missing:
        raise OpenJiuwenCompatibilityError(
            "OpenJiuwen 0.1.15 sandbox contract is incomplete: "
            + ", ".join(sorted(missing))
        )

    logger.info(
        "OpenJiuwen sandbox API validated, agent_sandbox_version=%s, provider=aio",
        agent_sandbox_version,
    )
    return OpenJiuwenSandboxAPI(
        SysOperationCard=SysOperationCard,
        OperationMode=OperationMode,
        SandboxGatewayConfig=SandboxGatewayConfig,
        SandboxIsolationConfig=SandboxIsolationConfig,
        PreDeployLauncherConfig=PreDeployLauncherConfig,
        ContainerScope=ContainerScope,
        SandboxRegistry=SandboxRegistry,
        Runner=Runner,
    )


def _validate_public_runtime_contract(
    *,
    ReActAgentConfig: Any,
    ContextEngine: Any,
    Runner: Any,
    create_agent_session: Any,
) -> None:
    """Validate the public 0.1.15 runtime surface used by the adapter."""
    missing: list[str] = []
    config_fields = set(getattr(ReActAgentConfig, "model_fields", {}))
    for field_name in {"model_name", "model_provider", "model_config_obj"}:
        if field_name not in config_fields:
            missing.append(f"ReActAgentConfig.{field_name}")

    for method_name in {"create_context", "clear_context"}:
        if not callable(getattr(ContextEngine, method_name, None)):
            missing.append(f"ContextEngine.{method_name}")

    if not callable(create_agent_session):
        missing.append("create_agent_session")

    resource_mgr = getattr(Runner, "resource_mgr", None)
    for method_name in {
        "add_mcp_server",
        "get_mcp_tool",
        "remove_mcp_server",
        "add_tool",
        "remove_tool",
    }:
        if not callable(getattr(resource_mgr, method_name, None)):
            missing.append(f"Runner.resource_mgr.{method_name}")

    if missing:
        raise OpenJiuwenCompatibilityError(
            "OpenJiuwen 0.1.15 public runtime contract is incomplete: "
            + ", ".join(sorted(missing))
        )


def flatten_message_content(raw_content: Any) -> str:
    """Flatten structured message content using Nexent completion semantics."""
    if isinstance(raw_content, str):
        return raw_content
    if isinstance(raw_content, list):
        parts: list[str] = []
        for item in raw_content:
            if isinstance(item, Mapping):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif "content" in item:
                    parts.append(str(item["content"]))
                else:
                    parts.append(str(dict(item)))
            else:
                parts.append(str(item))
        return "".join(parts)
    return "" if raw_content is None else str(raw_content)
