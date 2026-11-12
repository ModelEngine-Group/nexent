# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


from __future__ import annotations

import logging
from threading import Event, Lock
from typing import Any, Dict, List

from nexent.core.agents.contracts.config import ModelConfig
from nexent.core.agents.resources.child_owner import SubagentResources
from nexent.core.agents.resources.tools import ToolResources
from nexent.core.agents.resources.workspace import WorkspaceResources
from nexent.core.utils.observer import MessageObserver


logger = logging.getLogger(__name__)


class AgentResources(ToolResources, WorkspaceResources, SubagentResources):
    """Run-local resource state shared by execution-core adapters."""

    def __init__(self, observer: MessageObserver,
                 model_config_list: List[ModelConfig],
                 stop_event: Event,
                 mcp_tool_collection=None,
                 redis_client=None,
                 sandbox_config=None,
                 minio_client=None,
                 conversation_id=None,
                 user_id=None,
                 tenant_id=None,
                 workspace_path=None,
                 workspace_run_id=None,
                 minio_files=None,
                 cancellation_scope=None,
                 user_context=None,
                 tool_fastpath_enabled=True,
                 tool_fastpath_allowed_tools=None, child_invocation_factory=None):
        """
        Initialize the shared run-scoped resources.

        Args:
            observer: MessageObserver instance
            model_config_list: List of model configurations
            stop_event: Threading event for stop control
            mcp_tool_collection: Optional MCP tool collection
            redis_client: Redis client for plan persistence
            sandbox_config: Optional SandboxConfig for sandbox isolation.
                When None, uses LocalPythonExecutor (backwards-compatible).
            minio_client: Optional MinIO client for output file sync.
                Required when sandbox_config.auto_sync_outputs is True.
            conversation_id: Optional conversation id for plan persistence.
            user_id: Optional user id for plan persistence.
            tenant_id: Optional tenant id for file isolation.
            workspace_path: Run-scoped host workspace path.
            workspace_run_id: Opaque run id used to validate cleanup scope.
            minio_files: Authorized files attached to the current request.
            cancellation_scope: Optional run-scoped cancellation registry.
            user_context: Optional caller user context (tenant/user/groups)
                passed through to tools for tool-side authorization.
            tool_fastpath_enabled: Enable restricted local actions before Docker initialization.
            tool_fastpath_allowed_tools: Approved official implementation IDs.
        """
        if not isinstance(observer, MessageObserver):
            raise TypeError("Create Observer Object with MessageObserver")

        self._child_invocation_factory = child_invocation_factory
        self._resources_closed = False
        self.core_run_info = None
        self.observer = observer
        self.model_config_list = model_config_list
        self.stop_event = stop_event
        self._sandbox_skill_cleanup_owner = self
        self.cancellation_scope = cancellation_scope
        self.mcp_tool_collection = mcp_tool_collection
        self.redis_client = redis_client
        self.sandbox_config = sandbox_config
        self.tool_fastpath_enabled = tool_fastpath_enabled
        self.tool_fastpath_allowed_tools = tool_fastpath_allowed_tools
        self.minio_client = minio_client
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.workspace_path = workspace_path
        self.workspace_mapping = None
        if sandbox_config is not None and sandbox_config.workspace_mode == "bind" and workspace_path:
            from nexent.core.agents.sandbox.config import SandboxLevel

            if sandbox_config.level == SandboxLevel.DOCKER:
                self.workspace_mapping = sandbox_config.bind_workspace().for_run(workspace_path)
        self.workspace_run_id = workspace_run_id
        self.minio_files = list(minio_files or [])
        self.user_context = dict(user_context or {})
        self._workspace_uploads: List[Dict[str, Any]] = []
        self._workspace_uploaded_paths: set[str] = set()
        self._sandbox_executors: List[Any] = []
        self._sandbox_skill_runners: List[Any] = []
        self._tool_fastpath_executors: List[Any] = []
        self._subagent_invocations: Dict[Event, Any] = {}
        self._subagent_invocations_lock = Lock()
        self._subagent_invocations_closed = False

        self.agent = None

    def close(self):
        """Drain children before tearing down owned workspace and executors."""
        if self._resources_closed:
            return
        self._close_subagent_invocations()
        try:
            self._finalize_file_workspace()
        finally:
            try:
                self._cleanup_file_workspace()
            finally:
                self._cleanup_sandbox()
                self._resources_closed = True
