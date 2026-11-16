# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
import inspect
import importlib.machinery
import types
import unittest
import json
import sys
import atexit
from pathlib import Path
from concurrent.futures import Future
from unittest.mock import patch, MagicMock

_MODULE_PATCH_SENTINEL = object()
_MODULE_PATCH_NAMES = [
    'boto3',
    'elasticsearch',
    'sqlalchemy',
    'sqlalchemy.create_engine',
    'sqlalchemy.orm',
    'sqlalchemy.dialects',
    'sqlalchemy.dialects.postgresql',
    'sqlalchemy.sql',
    'management.db.agent.repository',
    'management.db.tool.repository',
    'management.db.model.repository',
    'management.db.knowledge_base.repository',
    'management.db.client',
    'management.db.models',
    'management.services.model.invocation',
    'management.services.agent.prompt',
    'management.services.agent.service',
    'nexent',
    'nexent.core',
    'nexent.core.agent_names',
    'nexent.core.prompts',
    'nexent.core.agents.prompt',
    'nexent.core.agents.prompt.auxiliary',
    'nexent.core.agents.prompt.meta',
    'nexent.core.agents',
    'nexent.core.agents.agent_model',
    'nexent.core.concurrency',
    'nexent.storage',
    'nexent.storage.storage_client_factory',
    'nexent.storage.minio_config',
    'nexent.vector_database',
    'nexent.memory',
    'nexent.monitor',
    'infrastructure.concurrency',
]
_MODULE_PATCH_ORIGINALS = {
    name: sys.modules.get(name, _MODULE_PATCH_SENTINEL)
    for name in _MODULE_PATCH_NAMES
}


def _restore_patched_modules() -> None:
    for name, original in _MODULE_PATCH_ORIGINALS.items():
        if original is _MODULE_PATCH_SENTINEL:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


atexit.register(_restore_patched_modules)


class MockToolConfig:
    def __init__(self, *args, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def model_dump(self, **kwargs):
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

# Mock nexent module hierarchy BEFORE any backend imports that depend on it
nexent_mock = types.ModuleType('nexent')
nexent_mock.__path__ = [str(Path(__file__).resolve().parents[3] / 'sdk/nexent')]
nexent_core_mock = types.ModuleType('nexent.core')
nexent_core_mock.__path__ = [str(Path(__file__).resolve().parents[3] / 'sdk/nexent/core')]
nexent_core_agents_mock = MagicMock()
nexent_core_agents_mock.__path__ = [str(Path(__file__).resolve().parents[3] / 'sdk/nexent/core/agents')]
nexent_agent_model_mock = MagicMock()
nexent_agent_model_mock.ToolConfig = MockToolConfig
nexent_storage_mock = MagicMock()
nexent_storage_storage_client_factory_mock = MagicMock()
nexent_storage_minio_config_mock = MagicMock()
nexent_vector_database_mock = MagicMock()
nexent_memory_mock = MagicMock()
nexent_monitor_mock = MagicMock()

sys.modules['nexent'] = nexent_mock
sys.modules['nexent.core'] = nexent_core_mock
prompt_resource_stub = types.ModuleType('nexent.core.prompts')
def _load_sdk_resource(language, path):
    import yaml
    source = Path(__file__).resolve().parents[3] / "sdk/nexent/core/prompts" / language / f"{path}.yaml"
    return yaml.safe_load(source.read_text(encoding="utf-8"))
prompt_resource_stub.load_prompt = _load_sdk_resource
prompt_resource_stub.__path__ = [str(Path(__file__).resolve().parents[3] / 'sdk/nexent/core/prompts')]
def _render_test_prompt(source, parameters):
    from jinja2 import Environment, StrictUndefined
    return Environment(undefined=StrictUndefined).from_string(source).render(**parameters)
prompt_resource_stub.render_prompt_text = _render_test_prompt
sys.modules['nexent.core.prompts'] = prompt_resource_stub
sys.modules['nexent.core.agents'] = nexent_core_agents_mock
prompt_assembly_stub = types.ModuleType('nexent.core.agents.prompt')
prompt_assembly_stub.__path__ = [str(Path(__file__).resolve().parents[3] / 'sdk/nexent/core/agents/prompt')]
sys.modules['nexent.core.agents.prompt'] = prompt_assembly_stub
sys.modules['nexent.core.agents.agent_model'] = nexent_agent_model_mock
sys.modules['nexent.storage'] = nexent_storage_mock
sys.modules['nexent.storage.storage_client_factory'] = nexent_storage_storage_client_factory_mock
sys.modules['nexent.storage.minio_config'] = nexent_storage_minio_config_mock
sys.modules['nexent.vector_database'] = nexent_vector_database_mock
sys.modules['nexent.memory'] = nexent_memory_mock
sys.modules['nexent.monitor'] = nexent_monitor_mock

concurrency_stub = types.ModuleType("nexent.core.concurrency")


class _ManagedExecution:
    def __init__(self, execution_id="prompt-test"):
        self.execution_id = execution_id
        self.future = Future()


class _ManagedTaskSpec:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


concurrency_stub.ManagedExecution = _ManagedExecution
concurrency_stub.ManagedTaskSpec = _ManagedTaskSpec
sys.modules['nexent.core.concurrency'] = concurrency_stub

# Stub parallel_executor so that prompt_service can import ParallelExecutorTool
_parallel_executor_stub = types.ModuleType("nexent.core.tools.parallel_executor")
class _MockParallelExecutorTool:
    __name__ = "ParallelExecutorTool"
    name = "parallel_executor"
    description = "Execute multiple independent calls in parallel."
    description_zh = "并行执行多个互不依赖的调用。"
    inputs = {"tasks": {"type": "array"}}
    output_type = "any"

_mock_parallel_tool = _MockParallelExecutorTool
_parallel_executor_stub.ParallelExecutorTool = _mock_parallel_tool
sys.modules["nexent.core.tools.parallel_executor"] = _parallel_executor_stub

# Mock external dependencies
sys.modules['boto3'] = MagicMock()
sys.modules['elasticsearch'] = MagicMock()
sys.modules['sqlalchemy'] = MagicMock()
sys.modules['sqlalchemy.create_engine'] = MagicMock()
sys.modules['sqlalchemy.orm'] = MagicMock()
sys.modules['sqlalchemy.dialects'] = MagicMock()
sys.modules['sqlalchemy.dialects.postgresql'] = MagicMock()
sys.modules['sqlalchemy.sql'] = MagicMock()


# DO NOT mock consts - import real ones
# The backend path is already in sys.path via sys.path.insert above

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.constants.environment import ENABLE_JIUWEN_SDK

# Mock boto3 and minio client before importing the module under test
import sys
boto3_module = types.ModuleType("boto3")
boto3_module.client = MagicMock()
boto3_module.resource = MagicMock()
boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
sys.modules['boto3'] = boto3_module

# Mock ElasticSearch before importing other modules
elasticsearch_mock = MagicMock()
sys.modules['elasticsearch'] = elasticsearch_mock

# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

minio_client_mock = MagicMock()
minio_client_mock._ensure_bucket_exists = MagicMock()
minio_client_mock.client = MagicMock()

# Mock database submodules BEFORE importing prompt_service
sys.modules['management.db.agent.repository'] = MagicMock()
sys.modules['management.db.tool.repository'] = MagicMock()
sys.modules['management.db.model.repository'] = MagicMock()
sys.modules['management.db.knowledge_base.repository'] = MagicMock()
mock_database_client = MagicMock()
mock_database_client.MinioClient.return_value = minio_client_mock
mock_database_client.minio_client = minio_client_mock
sys.modules['management.db.client'] = mock_database_client
from test.common.database_stubs import install_serialization_stub
install_serialization_stub(sys.modules["management.db.client"])
from test.common.database_stubs import install_serialization_stub
install_serialization_stub(sys.modules["management.db.client"])
sys.modules['management.db.client'] = mock_database_client
from test.common.database_stubs import install_serialization_stub
install_serialization_stub(sys.modules["management.db.client"])
sys.modules['management.db.models'] = MagicMock()

from jinja2 import StrictUndefined

# Mock utils
sys.modules['management.services.model.invocation'] = MagicMock()
sys.modules['management.services.agent.prompt'] = MagicMock()

# Mock services
sys.modules['management.services.agent.service'] = MagicMock()
thread_lifecycle_stub = types.ModuleType('infrastructure.concurrency')
thread_lifecycle_stub.config_thread_manager = MagicMock()


def _submit_prompt(_lane, _spec, fn, *args, **kwargs):
    execution = _ManagedExecution()
    try:
        execution.future.set_result(fn(*args, **kwargs))
    except BaseException as exc:
        execution.future.set_exception(exc)
    return execution


thread_lifecycle_stub.config_thread_manager.submit.side_effect = _submit_prompt
sys.modules['infrastructure.concurrency'] = thread_lifecycle_stub

from management.services.agent.prompt_generation import join_info_for_optimize_prompt_section, optimize_prompt_section_impl, _get_enabled_tool_descriptions, PromptOptimizationService, OptimizeRequest, OptimizeResult, _copy_bad_cases_with_scope_instruction, _resolve_knowledge_tool_capabilities


class TestPromptService(unittest.TestCase):

    def setUp(self):
        self.test_model_id = 1

    @patch('management.services.agent.prompt_generation.call_llm_for_system_prompt')
    @patch('nexent.core.agents.prompt.meta.load_prompt')
    @patch('management.services.agent.prompt_generation.query_tools_by_ids')
    @patch('management.services.agent.prompt_generation.search_agent_info_by_agent_id')
    def test_optimize_prompt_section_impl_success(
        self,
        mock_search_agent_info,
        mock_query_tools,
        mock_get_prompt_template,
        mock_call_llm,
    ):
        mock_query_tools.return_value = [
            {"name": "tool1", "description": "Tool 1", "inputs": "{}", "output_type": "text"}
        ]
        mock_search_agent_info.return_value = {"name": "assistant1", "description": "Assistant 1"}
        mock_get_prompt_template.side_effect = lambda language, path: _load_sdk_resource(language, path) if path != "meta/optimize_prompt" else {
            "OPTIMIZE_SYSTEM_PROMPT": "Optimize section",
            "OPTIMIZE_USER_PROMPT": "Section {{ section_type }} {{ current_content }} {{ feedback }}"
        }
        mock_call_llm.return_value = "Optimized content"

        result = optimize_prompt_section_impl(
            agent_id=1,
            model_id=2,
            task_description="Build an agent",
            tenant_id="tenant-1",
            language="en",
            section_type="duty",
            section_title="Agent Role",
            current_content="Original duty",
            feedback="Make it more specific",
            tool_ids=[10],
            sub_agent_ids=[20],
            knowledge_base_display_names=["kb-a"],
        )

        self.assertEqual(result["section_type"], "duty")
        self.assertEqual(result["original_content"], "Original duty")
        self.assertEqual(result["optimized_content"], "Optimized content")
        mock_query_tools.assert_called_once_with([10])
        mock_search_agent_info.assert_called_once_with(agent_id=20, tenant_id="tenant-1")
        mock_call_llm.assert_called_once()

    def test_optimize_prompt_section_impl_requires_feedback(self):
        with self.assertRaises(AppException) as context:
            optimize_prompt_section_impl(
                agent_id=1,
                model_id=2,
                task_description="Build an agent",
                tenant_id="tenant-1",
                language="en",
                section_type="duty",
                section_title="Agent Role",
                current_content="Original duty",
                feedback="",
            )

        self.assertEqual(
            context.exception.error_code,
            ErrorCode.COMMON_MISSING_REQUIRED_FIELD
        )

    @patch('nexent.core.agents.prompt.meta.render_prompt_text')
    def test_join_info_for_optimize_prompt_section(self, mock_template):
        mock_template_instance = mock_template
        mock_template_instance.return_value = "Rendered optimize content"
        mock_template_instance.side_effect = lambda source, parameters: mock_template_instance.return_value if "task_description" in parameters else _render_test_prompt(source, parameters)

        result = join_info_for_optimize_prompt_section(
            prompt_for_optimize={"OPTIMIZE_USER_PROMPT": "Template"},
            section_type="constraint",
            section_title="Usage Requirements",
            task_description="Task description",
            current_content="Original content",
            feedback="Be clearer",
            tool_info_list=[
                {"name": "tool1", "description": "Tool 1", "inputs": "{}", "output_type": "text"}
            ],
            sub_agent_info_list=[
                {"name": "assistant1", "description": "Assistant 1"}
            ],
            language="en",
            knowledge_base_display_names=["kb-a", "kb-b"],
        )

        self.assertEqual(result, "Rendered optimize content")
        template_vars = mock_template_instance.call_args[0][1]
        self.assertEqual(template_vars["section_type"], "constraint")
        self.assertEqual(template_vars["current_content"], "Original content")
        self.assertEqual(template_vars["feedback"], "Be clearer")
        self.assertEqual(template_vars["knowledge_base_names"], "")


    @patch('management.services.agent.prompt_generation.query_tools_by_ids')
    @patch('management.services.agent.prompt_generation.get_enable_tool_id_by_agent_id')
    def test__get_enabled_tool_descriptions(
        self,
        mock_get_enable_tool_ids,
        mock_query_tools,
    ):
        """DB results should be returned with parallel_executor appended."""
        mock_get_enable_tool_ids.return_value = [1, 2]
        tools = [{"tool_id": 1}, {"tool_id": 2}]
        mock_query_tools.return_value = tools

        result = _get_enabled_tool_descriptions(
            agent_id=123, tenant_id="tenant-x"
        )

        mock_get_enable_tool_ids.assert_called_once_with(
            agent_id=123, tenant_id="tenant-x"
        )
        mock_query_tools.assert_called_once_with([1, 2])
        # parallel_executor is always injected
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], {"tool_id": 1})
        self.assertEqual(result[1], {"tool_id": 2})
        self.assertEqual(result[2]["name"], "parallel_executor")

    @patch('management.services.agent.prompt_generation.query_tools_by_ids')
    @patch('management.services.agent.prompt_generation.get_enable_tool_id_by_agent_id')
    def test_get_enabled_tool_description_parallel_executor_not_duplicated(
        self,
        mock_get_enable_tool_ids,
        mock_query_tools,
    ):
        """When parallel_executor is already in DB results, it is not duplicated."""
        mock_get_enable_tool_ids.return_value = [1]
        tools = [{"name": "parallel_executor", "tool_id": 99}]
        mock_query_tools.return_value = tools

        result = _get_enabled_tool_descriptions(
            agent_id=1, tenant_id="t"
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tool_id"], 99)

    @patch('management.services.agent.prompt_generation.search_agent_info_by_agent_id')
    @patch('management.services.agent.prompt_generation.query_sub_agents_id_list')
    def test__get_enabled_sub_agent_descriptions(
        self,
        mock_query_sub_ids,
        mock_search_agent,
    ):
        """Wrapper should fetch sub-agent IDs then hydrate them with info."""
        from management.services.agent.prompt_generation import _get_enabled_sub_agent_descriptions

        mock_query_sub_ids.return_value = [10, 20]
        mock_search_agent.side_effect = [
            {"agent_id": 10, "name": "A"},
            {"agent_id": 20, "name": "B"},
        ]

        result = _get_enabled_sub_agent_descriptions(
            agent_id=99, tenant_id="tenant-y"
        )

        mock_query_sub_ids.assert_called_once_with(
            main_agent_id=99, tenant_id="tenant-y"
        )
        self.assertEqual(mock_search_agent.call_count, 2)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["agent_id"], 10)
        self.assertEqual(result[1]["agent_id"], 20)

    # ==================== Additional tests for higher coverage ====================


    @patch('management.services.agent.prompt_generation.query_tools_by_ids')
    @patch('management.services.agent.prompt_generation.get_enable_tool_id_by_agent_id')
    def test__get_enabled_tool_descriptions_empty_tool_ids(
        self,
        mock_get_enable_tool_ids,
        mock_query_tools,
    ):
        """Test _get_enabled_tool_descriptions with empty tool IDs"""
        from management.services.agent.prompt_generation import _get_enabled_tool_descriptions

        # Setup - return empty list
        mock_get_enable_tool_ids.return_value = []
        mock_query_tools.return_value = []

        result = _get_enabled_tool_descriptions(
            agent_id=123, tenant_id="tenant-x"
        )

        # Should return empty list
        self.assertEqual(result, [])

    @patch('management.services.agent.prompt_generation.search_agent_info_by_agent_id')
    @patch('management.services.agent.prompt_generation.query_sub_agents_id_list')
    def test__get_enabled_sub_agent_descriptions_empty(
        self,
        mock_query_sub_ids,
        mock_search_agent,
    ):
        """Test _get_enabled_sub_agent_descriptions with empty sub-agent IDs"""
        from management.services.agent.prompt_generation import _get_enabled_sub_agent_descriptions

        # Setup - return empty list
        mock_query_sub_ids.return_value = []

        result = _get_enabled_sub_agent_descriptions(
            agent_id=99, tenant_id="tenant-y"
        )

        # Should return empty list
        self.assertEqual(result, [])
        mock_search_agent.assert_not_called()


    # ==================== Coverage gap tests ====================

    def test_optimize_prompt_section_impl_invalid_section_type(self):
        """Test that invalid section_type raises AppException"""
        with self.assertRaises(AppException) as context:
            optimize_prompt_section_impl(
                agent_id=1,
                model_id=2,
                task_description="Build an agent",
                tenant_id="tenant-1",
                language="en",
                section_type="invalid_type",
                section_title="Some Title",
                current_content="Original content",
                feedback="Some feedback",
            )
        self.assertEqual(context.exception.error_code, ErrorCode.COMMON_PARAMETER_INVALID)

    def test_optimize_prompt_section_impl_missing_current_content(self):
        """Test that missing current_content raises AppException"""
        with self.assertRaises(AppException) as context:
            optimize_prompt_section_impl(
                agent_id=1,
                model_id=2,
                task_description="Build an agent",
                tenant_id="tenant-1",
                language="en",
                section_type="duty",
                section_title="Agent Role",
                current_content="",
                feedback="Some feedback",
            )
        self.assertEqual(context.exception.error_code, ErrorCode.COMMON_MISSING_REQUIRED_FIELD)

    def test_optimize_prompt_section_impl_empty_result(self):
        """Test that empty LLM result raises AppException"""
        with patch('management.services.agent.prompt_generation.call_llm_for_system_prompt') as mock_call_llm:
            with patch('nexent.core.agents.prompt.meta.load_prompt') as mock_template:
                mock_template.side_effect = lambda language, path: _load_sdk_resource(language, path) if path != "meta/optimize_prompt" else {
                    "OPTIMIZE_SYSTEM_PROMPT": "System prompt",
                    "OPTIMIZE_USER_PROMPT": "User prompt",
                }
                mock_call_llm.return_value = ""

                with self.assertRaises(AppException) as context:
                    optimize_prompt_section_impl(
                        agent_id=1,
                        model_id=2,
                        task_description="Build an agent",
                        tenant_id="tenant-1",
                        language="en",
                        section_type="duty",
                        section_title="Agent Role",
                        current_content="Original content",
                        feedback="Make it better",
                    )
                self.assertEqual(
                    context.exception.error_code,
                    ErrorCode.MODEL_PROMPT_GENERATION_FAILED
                )

    def test_optimize_prompt_section_impl_uses_default_title(self):
        """Test that section_title defaults when not provided"""
        with patch('management.services.agent.prompt_generation.call_llm_for_system_prompt') as mock_call_llm:
            with patch('nexent.core.agents.prompt.meta.load_prompt') as mock_template:
                with patch('management.services.agent.prompt_generation.join_info_for_optimize_prompt_section') as mock_join:
                    mock_template.side_effect = lambda language, path: _load_sdk_resource(language, path) if path != "meta/optimize_prompt" else {
                        "OPTIMIZE_SYSTEM_PROMPT": "System prompt",
                        "OPTIMIZE_USER_PROMPT": "User prompt",
                    }
                    mock_call_llm.return_value = "Optimized"
                    mock_join.return_value = "joined"

                    result = optimize_prompt_section_impl(
                        agent_id=1,
                        model_id=2,
                        task_description="Build an agent",
                        tenant_id="tenant-1",
                        language="zh",
                        section_type="duty",
                        section_title=None,
                        current_content="Original content",
                        feedback="Make it better",
                    )
                    self.assertEqual(result["section_title"], "智能体角色")

    @patch('nexent.core.agents.prompt.meta.render_prompt_text')
    def test_join_info_for_optimize_prompt_section_english(self, mock_template):
        """Test join_info_for_optimize_prompt_section with English language"""
        mock_instance = mock_template
        mock_instance.return_value = "Rendered"
        mock_instance.side_effect = lambda source, parameters: mock_instance.return_value if "task_description" in parameters else _render_test_prompt(source, parameters)

        result = join_info_for_optimize_prompt_section(
            prompt_for_optimize={"OPTIMIZE_USER_PROMPT": "Template {{ section_title }}"},
            section_type="constraint",
            section_title="Requirements",
            task_description="Task",
            current_content="Content",
            feedback="Feedback",
            tool_info_list=[{"name": "t1", "description": "d", "inputs": "i", "output_type": "o"}],
            sub_agent_info_list=[{"name": "a1", "description": "desc"}],
            language="en",
            knowledge_base_display_names=["kb1"],
        )

        self.assertEqual(result, "Rendered")
        render_args = mock_instance.call_args[0][1]
        self.assertEqual(render_args["section_type"], "constraint")
        self.assertEqual(render_args["knowledge_base_names"], "")

    @patch('nexent.core.agents.prompt.meta.render_prompt_text')
    def test_join_info_for_optimize_prompt_section_without_kb(self, mock_template):
        """Test join_info_for_optimize_prompt_section without knowledge base"""
        mock_instance = mock_template
        mock_instance.return_value = "Rendered"
        mock_instance.side_effect = lambda source, parameters: mock_instance.return_value if "task_description" in parameters else _render_test_prompt(source, parameters)

        result = join_info_for_optimize_prompt_section(
            prompt_for_optimize={"OPTIMIZE_USER_PROMPT": "Template"},
            section_type="duty",
            section_title="Role",
            task_description="Task",
            current_content="Content",
            feedback="Feedback",
            tool_info_list=[],
            sub_agent_info_list=[],
            language="zh",
            knowledge_base_display_names=None,
        )

        render_args = mock_instance.call_args[0][1]
        self.assertEqual(render_args["knowledge_base_names"], "")

    def test_default_prompt_section_title_zh(self):
        """Test _default_prompt_section_title with Chinese language"""
        from management.services.agent.prompt_generation import _default_prompt_section_title
        self.assertEqual(_default_prompt_section_title("duty", "zh"), "智能体角色")
        self.assertEqual(_default_prompt_section_title("constraint", "zh"), "使用要求")
        self.assertEqual(_default_prompt_section_title("few_shots", "zh"), "示例")

    def test_default_prompt_section_title_en(self):
        """Test _default_prompt_section_title with English language"""
        from management.services.agent.prompt_generation import _default_prompt_section_title
        self.assertEqual(_default_prompt_section_title("duty", "en"), "Agent Role")
        self.assertEqual(_default_prompt_section_title("constraint", "en"), "Usage Requirements")
        self.assertEqual(_default_prompt_section_title("few_shots", "en"), "Few Shots")

    def test_default_prompt_section_title_unknown_lang(self):
        """Test _default_prompt_section_title falls back to ZH for unknown language"""
        from management.services.agent.prompt_generation import _default_prompt_section_title
        self.assertEqual(_default_prompt_section_title("duty", "xx"), "智能体角色")
        self.assertEqual(_default_prompt_section_title("unknown_type", "en"), "unknown_type")

    @patch('management.services.agent.prompt_generation.query_tools_by_ids')
    @patch('management.services.agent.prompt_generation.get_enable_tool_id_by_agent_id')
    def test_resolve_prompt_tools_empty_ids(self, mock_get_ids, mock_query_tools):
        """Test _resolve_prompt_tools with empty tool_ids uses DB fallback"""
        from management.services.agent.prompt_generation import _resolve_prompt_tools
        mock_get_ids.return_value = [1, 2]
        mock_query_tools.return_value = [{"name": "tool1"}]

        result = _resolve_prompt_tools(agent_id=123, tenant_id="tenant-x", tool_ids=[])

        mock_get_ids.assert_called_once()
        mock_query_tools.assert_called_once_with([1, 2])

    @patch('management.services.agent.prompt_generation.search_agent_info_by_agent_id')
    def test_resolve_prompt_sub_agents_empty_ids(self, mock_search):
        """Test _resolve_prompt_sub_agents with empty sub_agent_ids uses DB fallback"""
        from management.services.agent.prompt_generation import _resolve_prompt_sub_agents
        mock_search.return_value = {"name": "sub1"}

        result = _resolve_prompt_sub_agents(agent_id=123, tenant_id="tenant-x", sub_agent_ids=[])

        mock_search.assert_not_called()

    @patch('management.services.agent.prompt_generation.search_agent_info_by_agent_id')
    def test_resolve_prompt_sub_agents_with_ids(self, mock_search):
        """Test _resolve_prompt_sub_agents with sub_agent_ids queries DB"""
        from management.services.agent.prompt_generation import _resolve_prompt_sub_agents
        mock_search.return_value = {"name": "sub1"}

        result = _resolve_prompt_sub_agents(agent_id=123, tenant_id="tenant-x", sub_agent_ids=[10, 20])

        self.assertEqual(mock_search.call_count, 2)
        self.assertEqual(len(result), 2)

    @patch('management.services.agent.prompt_generation.search_agent_info_by_agent_id')
    def test_resolve_prompt_sub_agents_exception_handling(self, mock_search):
        """Test _resolve_prompt_sub_agents handles exception gracefully"""
        from management.services.agent.prompt_generation import _resolve_prompt_sub_agents
        mock_search.side_effect = [Exception("DB error"), {"name": "sub2"}]

        result = _resolve_prompt_sub_agents(agent_id=123, tenant_id="tenant-x", sub_agent_ids=[10, 20])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "sub2")


class TestPromptOptimizationService(unittest.TestCase):
    """Tests for PromptOptimizationService Jiuwen SDK integration"""

    @patch('management.services.agent.prompt_generation.optimize_prompt_section_impl')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', False)
    def test_optimize_nexent_fallback_general_mode(self, mock_impl):
        """nexent 模式: mode=general 应该调用 optimize_prompt_section_impl"""
        mock_impl.return_value = {
            "section_type": "duty",
            "section_title": "智能体角色",
            "original_content": "old",
            "optimized_content": "new",
        }

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="智能体角色",
            current_content="old", feedback="improve",
            mode="general",
        )
        result = service.optimize(req)

        self.assertEqual(result.source, "nexent")
        self.assertEqual(result.optimized_content, "new")
        mock_impl.assert_called_once()

    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', False)
    def test_optimize_nexent_fallback_insert_mode_raises(self):
        """nexent 模式: mode=insert 应该抛出 NexentCapabilityError"""
        from adapters.exception import NexentCapabilityError

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="title",
            current_content="old", feedback="improve",
            mode="insert",
        )
        with self.assertRaises(NexentCapabilityError) as ctx:
            service.optimize(req)
        self.assertIn("insert", str(ctx.exception))

    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', False)
    def test_optimize_nexent_fallback_select_mode_raises(self):
        """nexent 模式: mode=select 应该抛出 NexentCapabilityError"""
        from adapters.exception import NexentCapabilityError

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="title",
            current_content="old", feedback="improve",
            mode="select",
        )
        with self.assertRaises(NexentCapabilityError):
            service.optimize(req)

    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', False)
    def test_optimize_badcase_nexent_raises(self):
        """nexent 模式: badcase 优化应该抛出 NexentCapabilityError"""
        from adapters.exception import NexentCapabilityError

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        with self.assertRaises(NexentCapabilityError) as ctx:
            service.optimize_badcase(
                current_content="old",
                bad_cases=[{"question": "Q1", "answer": "A1"}],
                agent_id=1, section_type="duty", section_title="title",
            )
        self.assertIn("badcase", str(ctx.exception))

    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_is_jiuwen_mode_available_env_disabled(self):
        """开关关闭时 Jiuwen SDK 不可用"""
        from contracts.constants.environment import ENABLE_JIUWEN_SDK

        # Patch ENABLE_JIUWEN_SDK to False
        with patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', False):
            service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
            self.assertFalse(service.is_jiuwen_mode_available())

    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_is_jiuwen_mode_available_openjiuwen_missing(self):
        """openjiuwen 未安装时 Jiuwen SDK 不可用"""
        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        with patch('builtins.__import__', side_effect=ModuleNotFoundError("No module named 'openjiuwen'")):
            self.assertFalse(service.is_jiuwen_mode_available())

    def test_optimize_request_dataclass_fields(self):
        """OptimizeRequest dataclass 所有字段正确"""
        req = OptimizeRequest(
            agent_id=1, model_id=2, task_description="task",
            section_type="duty", section_title="title",
            current_content="old", feedback="improve",
            mode="insert", start_pos=5, end_pos=10,
            tool_ids=[1, 2], sub_agent_ids=[3],
            knowledge_base_display_names=["kb1"],
        )
        self.assertEqual(req.agent_id, 1)
        self.assertEqual(req.model_id, 2)
        self.assertEqual(req.mode, "insert")
        self.assertEqual(req.start_pos, 5)
        self.assertEqual(req.end_pos, 10)
        self.assertEqual(req.tool_ids, [1, 2])
        self.assertEqual(req.sub_agent_ids, [3])
        self.assertEqual(req.knowledge_base_display_names, ["kb1"])

    def test_optimize_result_dataclass_fields(self):
        """OptimizeResult dataclass 所有字段正确"""
        res = OptimizeResult(
            optimized_content="new",
            source="jiuwen",
            section_type="duty",
            section_title="title",
            original_content="old",
        )
        self.assertEqual(res.optimized_content, "new")
        self.assertEqual(res.source, "jiuwen")
        self.assertEqual(res.section_type, "duty")
        self.assertEqual(res.section_title, "title")
        self.assertEqual(res.original_content, "old")


# ==================== Tests for aidp_kb_display_names parameter ====================


class TestJoinInfoForOptimizePromptSectionAidpKbNames(unittest.TestCase):
    """Test aidp_kb_names in join_info_for_optimize_prompt_section template context."""

    @patch('nexent.core.agents.prompt.meta.render_prompt_text')
    def test_aidp_kb_display_names_passed_to_template_context(self, mock_template):
        mock_template_instance = mock_template
        mock_template_instance.return_value = "rendered"
        mock_template_instance.side_effect = lambda source, parameters: mock_template_instance.return_value if "task_description" in parameters else _render_test_prompt(source, parameters)

        join_info_for_optimize_prompt_section(
            prompt_for_optimize={"OPTIMIZE_USER_PROMPT": "tmpl"},
            section_type="duty",
            section_title="Duties",
            task_description="task",
            current_content="content",
            feedback="feedback",
            tool_info_list=[
                {"name": "t", "description": "d", "inputs": "{}", "output_type": "text"}
            ],
            sub_agent_info_list=[
                {"name": "a", "description": "d"}
            ],
            language="en",
            aidp_kb_display_names=["aidp-kb-a", "aidp-kb-b"],
        )

        template_vars = mock_template_instance.call_args[0][1]
        self.assertEqual(template_vars["aidp_kb_names"], "")


# ==================== Coverage boost tests ====================


class TestExtractJsonObject(unittest.TestCase):
    """Tests for _extract_json_object helper (lines 486-513)."""

    def test_returns_none_for_empty_input(self):
        from management.services.agent.prompt_generation import _extract_json_object
        self.assertIsNone(_extract_json_object(""))
        self.assertIsNone(_extract_json_object(None))
        self.assertIsNone(_extract_json_object("   "))

    def test_returns_none_when_no_braces(self):
        from management.services.agent.prompt_generation import _extract_json_object
        self.assertIsNone(_extract_json_object("just plain text no json"))

    def test_extracts_simple_json_object(self):
        from management.services.agent.prompt_generation import _extract_json_object
        raw = 'some text {"key": "value"} more text'
        result = _extract_json_object(raw)
        self.assertEqual(result, {"key": "value"})

    def test_extracts_nested_json(self):
        from management.services.agent.prompt_generation import _extract_json_object
        raw = '{"type": "single", "candidates": [{"pattern": "\\d+", "desc": "digits"}]}'
        result = _extract_json_object(raw)
        self.assertEqual(result["type"], "single")
        self.assertEqual(len(result["candidates"]), 1)

    def test_handles_single_quotes_fallback(self):
        from management.services.agent.prompt_generation import _extract_json_object
        raw = "{'type': 'single', 'count': 1}"
        result = _extract_json_object(raw)
        self.assertEqual(result["type"], "single")
        self.assertEqual(result["count"], 1)

    def test_handles_trailing_commas_fallback(self):
        from management.services.agent.prompt_generation import _extract_json_object
        raw = '{"type": "single", "items": [1, 2,],}'
        result = _extract_json_object(raw)
        # Should fix trailing commas and parse successfully
        self.assertIsNotNone(result)

    def test_handles_invalid_json_escape_fallback(self):
        from management.services.agent.prompt_generation import _extract_json_object
        # LLM often outputs \d \w etc. with single backslash (invalid JSON)
        raw = r'{"pattern": "\d+\.\d+"}'
        result = _extract_json_object(raw)
        self.assertIsNotNone(result)
        self.assertIn("pattern", result)

    def test_returns_none_for_completely_invalid_json(self):
        from management.services.agent.prompt_generation import _extract_json_object
        raw = "{not json at all!!!"
        result = _extract_json_object(raw)
        self.assertIsNone(result)

    def test_end_before_start_returns_none(self):
        from management.services.agent.prompt_generation import _extract_json_object
        raw = "} something {"
        result = _extract_json_object(raw)
        self.assertIsNone(result)


class TestGenerateGuardrailRulesImpl(unittest.TestCase):
    """Tests for generate_guardrail_rules_impl (lines 547-586)."""

    def test_empty_description_raises(self):
        from management.services.agent.prompt_generation import generate_guardrail_rules_impl
        with self.assertRaises(AppException) as ctx:
            generate_guardrail_rules_impl(
                description="",
                model_id=1,
                tenant_id="t",
            )
        self.assertEqual(ctx.exception.error_code, ErrorCode.COMMON_MISSING_REQUIRED_FIELD)

    def test_whitespace_description_raises(self):
        from management.services.agent.prompt_generation import generate_guardrail_rules_impl
        with self.assertRaises(AppException) as ctx:
            generate_guardrail_rules_impl(
                description="   ",
                model_id=1,
                tenant_id="t",
            )
        self.assertEqual(ctx.exception.error_code, ErrorCode.COMMON_MISSING_REQUIRED_FIELD)

    @patch('management.services.agent.prompt_generation.call_llm_for_system_prompt')
    @patch('nexent.core.agents.prompt.auxiliary.load_prompt')
    def test_empty_llm_response_raises(self, mock_template, mock_llm):
        from management.services.agent.prompt_generation import generate_guardrail_rules_impl
        mock_template.return_value = {
            "GUARDRAIL_USER_PROMPT": "prompt {{ description }}",
            "GUARDRAIL_SYSTEM_PROMPT": "system",
        }
        mock_llm.return_value = "   "

        with self.assertRaises(AppException) as ctx:
            generate_guardrail_rules_impl(
                description="block phone numbers",
                model_id=1,
                tenant_id="t",
            )
        self.assertEqual(ctx.exception.error_code, ErrorCode.MODEL_PROMPT_GENERATION_FAILED)

    @patch('management.services.agent.prompt_generation.call_llm_for_system_prompt')
    @patch('nexent.core.agents.prompt.auxiliary.load_prompt')
    def test_invalid_json_response_raises(self, mock_template, mock_llm):
        from management.services.agent.prompt_generation import generate_guardrail_rules_impl
        mock_template.return_value = {
            "GUARDRAIL_USER_PROMPT": "prompt {{ description }}",
            "GUARDRAIL_SYSTEM_PROMPT": "system",
        }
        mock_llm.return_value = "no json here at all"

        with self.assertRaises(AppException) as ctx:
            generate_guardrail_rules_impl(
                description="block phone numbers",
                model_id=1,
                tenant_id="t",
            )
        self.assertEqual(ctx.exception.error_code, ErrorCode.MODEL_PROMPT_GENERATION_FAILED)

    @patch('management.services.agent.prompt_generation.call_llm_for_system_prompt')
    @patch('nexent.core.agents.prompt.auxiliary.load_prompt')
    def test_unknown_type_raises(self, mock_template, mock_llm):
        from management.services.agent.prompt_generation import generate_guardrail_rules_impl
        mock_template.return_value = {
            "GUARDRAIL_USER_PROMPT": "prompt {{ description }}",
            "GUARDRAIL_SYSTEM_PROMPT": "system",
        }
        mock_llm.return_value = '{"type": "unknown_type", "data": []}'

        with self.assertRaises(AppException) as ctx:
            generate_guardrail_rules_impl(
                description="block phone numbers",
                model_id=1,
                tenant_id="t",
            )
        self.assertEqual(ctx.exception.error_code, ErrorCode.MODEL_PROMPT_GENERATION_FAILED)
        self.assertIn("Unknown guardrail result type", ctx.exception.message)

    @patch('management.services.agent.prompt_generation.call_llm_for_system_prompt')
    @patch('nexent.core.agents.prompt.auxiliary.load_prompt')
    def test_single_type_success(self, mock_template, mock_llm):
        from management.services.agent.prompt_generation import generate_guardrail_rules_impl
        mock_template.return_value = {
            "GUARDRAIL_USER_PROMPT": "prompt {{ description }}",
            "GUARDRAIL_SYSTEM_PROMPT": "system",
        }
        mock_llm.return_value = '{"type": "single", "candidates": [{"pattern": "1[3-9]\\d{9}", "desc": "phone"}]}'

        result = generate_guardrail_rules_impl(
            description="block phone numbers",
            model_id=1,
            tenant_id="t",
        )
        self.assertEqual(result["type"], "single")
        self.assertIsInstance(result["candidates"], list)

    @patch('management.services.agent.prompt_generation.call_llm_for_system_prompt')
    @patch('nexent.core.agents.prompt.auxiliary.load_prompt')
    def test_multi_type_success(self, mock_template, mock_llm):
        from management.services.agent.prompt_generation import generate_guardrail_rules_impl
        mock_template.return_value = {
            "GUARDRAIL_USER_PROMPT": "prompt {{ description }}",
            "GUARDRAIL_SYSTEM_PROMPT": "system",
        }
        mock_llm.return_value = '{"type": "multi", "rules": [{"name": "r1", "pattern": "\\d", "severity": "high", "desc": "d"}]}'

        result = generate_guardrail_rules_impl(
            description="block sensitive patterns",
            model_id=1,
            tenant_id="t",
        )
        self.assertEqual(result["type"], "multi")
        self.assertIsInstance(result["rules"], list)

    @patch('management.services.agent.prompt_generation.call_llm_for_system_prompt')
    @patch('nexent.core.agents.prompt.auxiliary.load_prompt')
    def test_single_type_with_non_list_candidates(self, mock_template, mock_llm):
        from management.services.agent.prompt_generation import generate_guardrail_rules_impl
        mock_template.return_value = {
            "GUARDRAIL_USER_PROMPT": "prompt {{ description }}",
            "GUARDRAIL_SYSTEM_PROMPT": "system",
        }
        mock_llm.return_value = '{"type": "single", "candidates": "not_a_list"}'

        result = generate_guardrail_rules_impl(
            description="block phone numbers",
            model_id=1,
            tenant_id="t",
        )
        self.assertEqual(result["type"], "single")
        self.assertEqual(result["candidates"], [])

    @patch('management.services.agent.prompt_generation.call_llm_for_system_prompt')
    @patch('nexent.core.agents.prompt.auxiliary.load_prompt')
    def test_multi_type_with_non_list_rules(self, mock_template, mock_llm):
        from management.services.agent.prompt_generation import generate_guardrail_rules_impl
        mock_template.return_value = {
            "GUARDRAIL_USER_PROMPT": "prompt {{ description }}",
            "GUARDRAIL_SYSTEM_PROMPT": "system",
        }
        mock_llm.return_value = '{"type": "multi", "rules": "not_a_list"}'

        result = generate_guardrail_rules_impl(
            description="block sensitive patterns",
            model_id=1,
            tenant_id="t",
        )
        self.assertEqual(result["type"], "multi")
        self.assertEqual(result["rules"], [])


class TestPromptOptimizationServiceOptimizeFromDebug(unittest.TestCase):
    """Tests for PromptOptimizationService.optimize_from_debug (lines 1158-1215)."""

    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', False)
    def test_empty_feedback_raises(self):
        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        selected = type("S", (), {"user_question": "q", "assistant_answer": "a"})()
        with self.assertRaises(AppException) as ctx:
            service.optimize_from_debug(agent_id=1, feedback="", selected=selected)
        self.assertEqual(ctx.exception.error_code, ErrorCode.COMMON_MISSING_REQUIRED_FIELD)

    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', False)
    def test_whitespace_feedback_raises(self):
        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        selected = type("S", (), {"user_question": "q", "assistant_answer": "a"})()
        with self.assertRaises(AppException):
            service.optimize_from_debug(agent_id=1, feedback="   ", selected=selected)

    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', False)
    def test_jiuwen_unavailable_raises(self):
        from adapters.exception import NexentCapabilityError
        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        selected = type("S", (), {"user_question": "q", "assistant_answer": "a"})()
        with self.assertRaises(NexentCapabilityError):
            service.optimize_from_debug(agent_id=1, feedback="good feedback", selected=selected)

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.search_agent_info_by_agent_id')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_successful_optimize_from_debug(self, mock_search_agent, mock_get_adapter):
        from adapters.exception import JiuwenSDKError

        mock_search_agent.return_value = {
            "prompt": "Duty content",
        }

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize_badcase.return_value = "Optimized full prompt"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        selected = type("S", (), {"user_question": "What is X?", "assistant_answer": "X is Y"})()

        result = service.optimize_from_debug(
            agent_id=1, feedback="Make it more specific", selected=selected
        )

        self.assertEqual(result.optimized_content, "Optimized full prompt")
        self.assertEqual(result.source, "jiuwen")
        self.assertEqual(result.section_type, "full_prompt")
        mock_adapter_instance.optimize_badcase.assert_called_once()
        self.assertEqual(mock_adapter_instance.optimize_badcase.call_args.kwargs["prompt"], "Duty content")
        self.assertEqual(result.original_content, "Duty content")

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.search_agent_info_by_agent_id')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_optimize_from_debug_with_dict_selected(self, mock_search_agent, mock_get_adapter):
        """Test optimize_from_debug when selected is a dict rather than an object."""
        mock_search_agent.return_value = {
            "prompt": "Duty",
        }

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize_badcase.return_value = "Optimized"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")

        result = service.optimize_from_debug(
            agent_id=1,
            feedback="feedback text",
            selected={"user_question": "Q?", "assistant_answer": "A!"},
        )

        self.assertEqual(result.optimized_content, "Optimized")

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.search_agent_info_by_agent_id')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_optimize_from_debug_empty_prompt_raises(self, mock_search_agent, mock_get_adapter):
        """A missing unified prompt cannot fall back to legacy content or headings."""
        mock_search_agent.return_value = {
            "prompt": None,
            "constraint_prompt": "Poisoned legacy rule",
            "few_shots_prompt": "Poisoned legacy example",
        }
        mock_adapter_cls = MagicMock()
        mock_get_adapter.return_value = mock_adapter_cls
        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        selected = type("S", (), {"user_question": "q", "assistant_answer": "a"})()
        with self.assertRaises(AppException) as caught:
            service.optimize_from_debug(agent_id=1, feedback="feedback", selected=selected)
        self.assertEqual(caught.exception.error_code, ErrorCode.COMMON_MISSING_REQUIRED_FIELD)
        mock_adapter_cls.return_value.optimize_badcase.assert_not_called()

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.search_agent_info_by_agent_id')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_optimize_from_debug_adapter_none_raises(self, mock_search_agent, mock_get_adapter):
        """When _get_jiuwen_adapter_class returns None after is_jiuwen_mode_available check, raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError

        mock_search_agent.return_value = {
            "prompt": "Duty",
        }
        # First call (is_jiuwen_mode_available) returns a class, second call returns None
        mock_adapter_cls = MagicMock()
        mock_get_adapter.side_effect = [mock_adapter_cls, None]

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        selected = type("S", (), {"user_question": "q", "assistant_answer": "a"})()

        with self.assertRaises(JiuwenSDKError):
            service.optimize_from_debug(agent_id=1, feedback="feedback", selected=selected)


class TestPromptOptimizationServiceOptimizeJiuwen(unittest.TestCase):
    """Tests for PromptOptimizationService.optimize with Jiuwen SDK paths (lines 1238-1303)."""

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_general_mode(self, mock_get_adapter):
        """Jiuwen SDK general mode returns optimized content."""
        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "Optimized by Jiuwen"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="Original content", feedback="Improve this",
            mode="general",
        )

        result = service.optimize(req)

        self.assertEqual(result.source, "jiuwen")
        self.assertEqual(result.optimized_content, "Optimized by Jiuwen")
        self.assertEqual(result.original_content, "Original content")

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_insert_mode(self, mock_get_adapter):
        """Jiuwen SDK insert mode inserts text at start_pos."""
        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "INSERTED"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="ABCDE", feedback="insert here",
            mode="insert", start_pos=2,
        )

        result = service.optimize(req)

        self.assertEqual(result.optimized_content, "ABINSERTEDCDE")

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_select_mode(self, mock_get_adapter):
        """Jiuwen SDK select mode replaces selected range."""
        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "REPLACED"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="ABCDEF", feedback="replace this",
            mode="select", start_pos=1, end_pos=4,
        )

        result = service.optimize(req)

        # "ABCDEF"[:1] + "REPLACED" + "ABCDEF"[4:] = "A" + "REPLACED" + "EF"
        self.assertEqual(result.optimized_content, "AREPLACEDEF")

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_insert_no_start_pos_raises(self, mock_get_adapter):
        """Insert mode without start_pos raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "text"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="ABC", feedback="insert",
            mode="insert", start_pos=None,
        )

        # Call _optimize_with_jiuwen directly to bypass the fallback in optimize()
        with self.assertRaises(JiuwenSDKError):
            service._optimize_with_jiuwen(req)

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_insert_out_of_bounds_raises(self, mock_get_adapter):
        """Insert mode with out-of-bounds start_pos raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "text"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="ABC", feedback="insert",
            mode="insert", start_pos=100,
        )

        with self.assertRaises(JiuwenSDKError):
            service._optimize_with_jiuwen(req)

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_select_missing_positions_raises(self, mock_get_adapter):
        """Select mode without start_pos/end_pos raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "text"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="ABCDEF", feedback="select",
            mode="select", start_pos=None, end_pos=None,
        )

        with self.assertRaises(JiuwenSDKError):
            service._optimize_with_jiuwen(req)

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_select_non_int_positions_raises(self, mock_get_adapter):
        """Select mode with non-integer positions raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "text"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="ABCDEF", feedback="select",
            mode="select", start_pos="bad", end_pos="worse",
        )

        with self.assertRaises(JiuwenSDKError):
            service._optimize_with_jiuwen(req)

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_select_invalid_range_raises(self, mock_get_adapter):
        """Select mode with start >= end raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "text"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="ABCDEF", feedback="select",
            mode="select", start_pos=5, end_pos=2,
        )

        with self.assertRaises(JiuwenSDKError):
            service._optimize_with_jiuwen(req)

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_select_end_out_of_bounds_raises(self, mock_get_adapter):
        """Select mode with end_pos > length raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.return_value = "text"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="ABC", feedback="select",
            mode="select", start_pos=0, end_pos=100,
        )

        with self.assertRaises(JiuwenSDKError):
            service._optimize_with_jiuwen(req)

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_adapter_unavailable_raises(self, mock_get_adapter):
        """When adapter class is None in _optimize_with_jiuwen, raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError
        mock_get_adapter.return_value = None

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="old", feedback="improve",
            mode="general",
        )

        # Call _optimize_with_jiuwen directly to avoid the fallback chain
        with self.assertRaises(JiuwenSDKError):
            service._optimize_with_jiuwen(req)

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.optimize_prompt_section_impl')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_optimize_jiuwen_error_falls_back_to_nexent(self, mock_impl, mock_get_adapter):
        """When Jiuwen SDK raises JiuwenSDKError, falls back to nexent native."""
        from adapters.exception import JiuwenSDKError

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize.side_effect = JiuwenSDKError("SDK failed")
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        mock_impl.return_value = {
            "section_type": "duty",
            "section_title": "Role",
            "original_content": "old",
            "optimized_content": "nexent fallback",
        }

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        req = OptimizeRequest(
            agent_id=1, model_id=1, task_description="task",
            section_type="duty", section_title="Role",
            current_content="old", feedback="improve",
            mode="general",
        )

        result = service.optimize(req)
        self.assertEqual(result.optimized_content, "nexent fallback")


class TestPromptOptimizationServiceBadcaseJiuwen(unittest.TestCase):
    """Tests for optimize_badcase with Jiuwen SDK (lines 1354-1388)."""

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_badcase_jiuwen_success(self, mock_get_adapter):
        """Jiuwen SDK badcase optimization succeeds."""
        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize_badcase.return_value = "Badcase optimized"
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")
        result = service.optimize_badcase(
            current_content="Current prompt",
            bad_cases=[{"question": "Q", "answer": "A"}],
            agent_id=1,
            section_type="duty",
            section_title="Role",
        )

        self.assertEqual(result.source, "jiuwen")
        self.assertEqual(result.optimized_content, "Badcase optimized")
        self.assertEqual(result.original_content, "Current prompt")

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_badcase_jiuwen_fallback_on_error(self, mock_get_adapter):
        """When Jiuwen SDK badcase fails, falls back to nexent which raises NexentCapabilityError."""
        from adapters.exception import JiuwenSDKError, NexentCapabilityError

        mock_adapter_cls = MagicMock()
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.optimize_badcase.side_effect = JiuwenSDKError("badcase fail")
        mock_adapter_cls.return_value = mock_adapter_instance
        mock_get_adapter.return_value = mock_adapter_cls

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")

        # Fallback to nexent which raises NexentCapabilityError (no native badcase support)
        with self.assertRaises(NexentCapabilityError):
            service.optimize_badcase(
                current_content="Current prompt",
                bad_cases=[{"question": "Q", "answer": "A"}],
                agent_id=1,
                section_type="duty",
                section_title="Role",
            )

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    @patch('management.services.agent.prompt_generation.ENABLE_JIUWEN_SDK', True)
    def test_badcase_jiuwen_adapter_none_raises(self, mock_get_adapter):
        """When adapter class is None in badcase, raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError, NexentCapabilityError

        mock_get_adapter.return_value = None

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")

        # _optimize_badcase_with_jiuwen raises JiuwenSDKError, then fallback _optimize_badcase_with_nexent raises NexentCapabilityError
        with self.assertRaises(NexentCapabilityError):
            service.optimize_badcase(
                current_content="Current prompt",
                bad_cases=[{"question": "Q", "answer": "A"}],
                agent_id=1,
                section_type="duty",
                section_title="Role",
            )


class TestGetJiuwenAdapterClass(unittest.TestCase):
    """Tests for _get_jiuwen_adapter_class (line 53, 1375-1388)."""

    def test_returns_adapter_when_importable(self):
        """When adapters module has JiuwenSDKAdapter, return it."""
        from management.services.agent.prompt_generation import _get_jiuwen_adapter_class

        mock_adapter = MagicMock()
        mock_module = MagicMock()
        mock_module.JiuwenSDKAdapter = mock_adapter

        with patch.dict(sys.modules, {'adapters': mock_module}):
            result = _get_jiuwen_adapter_class()

        self.assertEqual(result, mock_adapter)

    def test_returns_none_when_not_importable(self):
        """When adapters module is not found, return None."""
        from management.services.agent.prompt_generation import _get_jiuwen_adapter_class

        with patch.dict(sys.modules, {'adapters': None}):
            with patch('builtins.__import__', side_effect=ModuleNotFoundError("No module named 'adapters'")):
                result = _get_jiuwen_adapter_class()

        self.assertIsNone(result)


class TestExtractJsonObjectEdgeCases(unittest.TestCase):
    """Additional edge case for _extract_json_object final fallback (lines 512-513)."""

    def test_utterly_broken_json_all_fallbacks_fail(self):
        """When all JSON repair strategies fail, return None (lines 512-513)."""
        from management.services.agent.prompt_generation import _extract_json_object
        # Snippet with unbalanced braces that confuses all three strategies
        raw = '{\\x not valid json ever }'
        result = _extract_json_object(raw)
        # All fallbacks fail - returns None
        self.assertIsNone(result)


class TestOptimizeBadcaseWithJiuwenDirect(unittest.TestCase):
    """Test _optimize_badcase_with_jiuwen when adapter unavailable (line 1377)."""

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    def test_badcase_jiuwen_adapter_none_raises_directly(self, mock_get_adapter):
        """When adapter class is None, _optimize_badcase_with_jiuwen raises JiuwenSDKError."""
        from adapters.exception import JiuwenSDKError
        mock_get_adapter.return_value = None

        service = PromptOptimizationService(model_id=1, tenant_id="t", language="zh")

        with self.assertRaises(JiuwenSDKError):
            service._optimize_badcase_with_jiuwen(
                current_content="prompt",
                bad_cases=[{"q": "Q", "a": "A"}],
                section_type="duty",
                section_title="Role",
            )


class TestKnowledgeAgnosticPromptRules(unittest.TestCase):
    def test_tool_capabilities_do_not_depend_on_resource_names(self):
        local, aidp = _resolve_knowledge_tool_capabilities([
            {"class_name": "KnowledgeBaseSearchTool", "name": "custom-local"},
            {"name": "aidp_search"},
        ])

        self.assertTrue(local)
        self.assertTrue(aidp)

    def test_bad_cases_are_copied_and_hardened(self):
        original = {"question": "Q", "answer": "A", "reason": "Improve it"}

        copied = _copy_bad_cases_with_scope_instruction([original], "en")

        self.assertEqual(original["reason"], "Improve it")
        self.assertIsNot(copied[0], original)
        self.assertIn("current conversation", copied[0]["reason"])
        self.assertIn("fixed index_names", copied[0]["reason"])

    @patch('management.services.agent.prompt_generation._get_jiuwen_adapter_class')
    def test_jiuwen_general_optimization_receives_scope_rule(self, mock_get_adapter):
        adapter = MagicMock()
        adapter.optimize.return_value = "optimized"
        adapter_class = MagicMock(return_value=adapter)
        mock_get_adapter.return_value = adapter_class
        service = PromptOptimizationService(model_id=1, tenant_id="t", language="en")
        request = OptimizeRequest(
            agent_id=1,
            model_id=1,
            task_description="task",
            section_type="duty",
            section_title="Role",
            current_content="prompt",
            feedback="Improve it",
        )

        service._optimize_with_jiuwen(request)

        feedback = adapter.optimize.call_args.kwargs["feedback"]
        self.assertIn("Improve it", feedback)
        self.assertIn("fixed kds_list", feedback)


def test_join_info_for_optimize_prompt_section_full_context(mocker):
    """Full tool/sub-agent rendering exercises knowledge capability flags and the scope instruction."""
    from jinja2 import Template as JinjaTemplate

    render_kwargs = {}
    mocked_template = MagicMock()
    mocked_template.render = MagicMock(side_effect=lambda *args, **kwargs: render_kwargs.update(kwargs or (args[0] if args else {})) or "rendered")

    prompt_for_optimize = {
        "OPTIMIZE_USER_PROMPT": "{{ section_type }} {{ task_description }} {{ tool_description }} {{ has_local_knowledge_tool }} {{ has_aidp_knowledge_tool }}"
    }
    with mocker.patch("nexent.core.agents.prompt.meta.render_prompt_text", side_effect=lambda source, parameters: mocked_template.render(parameters) if "task_description" in parameters else _render_test_prompt(source, parameters)):
        result = join_info_for_optimize_prompt_section(
            prompt_for_optimize=prompt_for_optimize,
            section_type="constraint",
            section_title="section-title",
            task_description="task",
            current_content="body",
            feedback="fb",
            tool_info_list=[
                {"name": "knowledge_base_search", "description": "kb tool", "inputs": "{}", "output_type": "string"},
                {"name": "aidp_search", "description": "aidp tool", "inputs": "{}", "output_type": "string"},
            ],
            sub_agent_info_list=[{"name": "sub-1", "description": "sub desc"}],
            language="zh",
            knowledge_base_display_names=["KB 1"],
            aidp_kb_display_names=["AIDP 1"],
        )

    assert result == "rendered"
    assert render_kwargs["has_local_knowledge_tool"] is True
    assert render_kwargs["has_aidp_knowledge_tool"] is True
    assert "knowledge_base_search" in render_kwargs["tool_description"]
    assert "优化后的内容不得新增或保留具体知识库名称" in render_kwargs["tool_description"]


def test_join_info_for_optimize_prompt_section_english_scope_instruction(mocker):
    from jinja2 import Template as JinjaTemplate

    render_kwargs = {}
    mocked_template = MagicMock()
    mocked_template.render = MagicMock(side_effect=lambda *args, **kwargs: render_kwargs.update(kwargs or (args[0] if args else {})) or "ok")

    with mocker.patch("nexent.core.agents.prompt.meta.render_prompt_text", side_effect=lambda source, parameters: mocked_template.render(parameters) if "task_description" in parameters else _render_test_prompt(source, parameters)):
        join_info_for_optimize_prompt_section(
            prompt_for_optimize={"OPTIMIZE_USER_PROMPT": "{{ tool_description }}"},
            section_type="constraint",
            section_title="t",
            task_description="task",
            current_content="c",
            feedback="f",
            tool_info_list=[{"name": "knowledge_base_search", "description": "d", "inputs": "{}", "output_type": "string"}],
            sub_agent_info_list=[],
            language="en",
        )

    assert "Inputs" in render_kwargs["tool_description"]
    assert "must not add or retain concrete knowledge base names" in render_kwargs["tool_description"]


def test_join_info_for_optimize_prompt_section_without_knowledge_tool_omits_scope_instruction(mocker):
    render_kwargs = {}
    mocked_template = MagicMock()
    mocked_template.render = MagicMock(
        side_effect=lambda *args, **kwargs: render_kwargs.update(kwargs or (args[0] if args else {})) or "ok"
    )

    with mocker.patch("nexent.core.agents.prompt.meta.render_prompt_text", side_effect=lambda source, parameters: mocked_template.render(parameters) if "task_description" in parameters else _render_test_prompt(source, parameters)):
        join_info_for_optimize_prompt_section(
            prompt_for_optimize={"OPTIMIZE_USER_PROMPT": "{{ tool_description }}"},
            section_type="constraint",
            section_title="t",
            task_description="task",
            current_content="c",
            feedback="f",
            tool_info_list=[{"name": "web_search", "description": "d", "inputs": "{}", "output_type": "string"}],
            sub_agent_info_list=[],
            language="zh",
        )

    assert "web_search" in render_kwargs["tool_description"]
    assert "优化后的内容不得新增或保留具体知识库名称" not in render_kwargs["tool_description"]
    assert "当前会话允许的知识库范围" not in render_kwargs["tool_description"]
