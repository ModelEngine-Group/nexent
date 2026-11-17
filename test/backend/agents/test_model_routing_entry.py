# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Entry-point integration tests for multi-model task routing.

These tests exercise ``create_agent_config`` with MODEL_ROUTING_ENABLED
explicitly on, proving the routing path actually changes the selected
model — the unit tests alone cannot (review finding P2 #4).  The stub
recipe mirrors TestCreateAgentConfig in test_create_agent_info.py, but
keeps the real AgentConfig so ``model_name`` is assertable.
"""

import sys
import types
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

import management.services.agent.preparation.compiler as preparation_compiler
from management.services.model import routing


def _record(model_id, name, **facts):
    record = {
        "model_id": model_id,
        "model_name": name,
        "display_name": name,
        "reasoning_supported": None,
        "enable_thinking": None,
        "context_window_tokens": None,
        "max_input_tokens": None,
        "connect_status": "available",
    }
    record.update(facts)
    return record


DEEP_FACTS = {"reasoning_supported": True, "context_window_tokens": 65536}
LONG_FACTS = {"reasoning_supported": False, "context_window_tokens": 262144}
QUICK_FACTS = {"reasoning_supported": False, "context_window_tokens": 32768}


@pytest.fixture(autouse=True)
def _isolated_rules(monkeypatch):
    """Pin the shipped rules file and isolate the rules cache."""

    from pathlib import Path

    shipped = (
        Path(__file__).resolve().parents[3]
        / "backend" / "configs" / "model_routing_rules.json"
    )
    import contracts.constants.environment as env_module

    monkeypatch.setattr(
        env_module, "MODEL_ROUTING_RULES_JSON_PATH", str(shipped), raising=False
    )
    routing.reset_rules_cache()
    yield
    routing.reset_rules_cache()


@pytest.mark.asyncio
class TestRoutingEntry:
    async def _run(self, monkeypatch, model_records, *, query, routing_enabled, **overrides):
        monkeypatch.setattr(
            preparation_compiler, "MODEL_ROUTING_ENABLED", routing_enabled
        )
        records_by_id = {r["model_id"]: r for r in model_records}

        def _get_model(model_id, **_kwargs):
            return records_by_id.get(model_id)

        memory_context = Mock(
            user_config=Mock(
                memory_switch=False,
                agent_share_option="always",
                disable_agent_ids=[],
                disable_user_agent_ids=[],
            ),
            memory_config={},
            tenant_id="tenant_1",
            user_id="user_1",
            agent_id="agent_1",
        )
        agent_info = {
            "name": "test_agent",
            "display_name": "知识助手",
            "description": "test description",
            "prompt": "test duty",
            "max_steps": 5,
            "model_ids": [r["model_id"] for r in model_records],
            "provide_run_summary": False,
            "enable_context_manager": False,
        }

        with patch.object(preparation_compiler, "search_agent_info_by_agent_id", return_value=agent_info), \
                patch.object(preparation_compiler, "query_sub_agent_relations", return_value=[]), \
                patch.object(preparation_compiler, "create_tool_config_list", return_value=[]), \
                patch.object(preparation_compiler, "tenant_config_manager") as mock_tenant_config, \
                patch.object(preparation_compiler, "build_memory_context", return_value=memory_context), \
                patch("management.services.agent.preparation.inputs.prepare_prompt_templates", new_callable=AsyncMock), \
                patch.object(preparation_compiler, "get_model_by_model_id", side_effect=_get_model), \
                patch.object(preparation_compiler, "build_context_inputs", return_value=[]), \
                patch.object(preparation_compiler, "_get_skills_for_template", return_value=[]), \
                patch.object(preparation_compiler, "_get_external_a2a_agents", return_value=[]), \
                patch.object(preparation_compiler, "_get_skill_script_tools", return_value=[]), \
                patch.object(preparation_compiler, "_resolve_input_budget", return_value=(32768, None, None)), \
                patch.object(preparation_compiler, "_resolve_context_budget", return_value=None), \
                patch.dict(sys.modules, {
                    'management.services.memory.records': MagicMock(
                        _resolve_tenant_embedding_model_info=MagicMock(return_value=None),
                    ),
                    'management.services.memory.context': MagicMock(
                        get_memory_context_service=MagicMock(
                            return_value=MagicMock(
                                build_context=AsyncMock(return_value=types.SimpleNamespace(
                                    tenant_long_term=(),
                                    user_long_term=(),
                                ))
                            )
                        ),
                    ),
                    'management.services.memory.provider': MagicMock(
                        build_memory_service_for_agent=MagicMock(return_value=None),
                    ),
                }), \
                patch.object(
                    preparation_compiler,
                    "ContextManagerConfig",
                    side_effect=lambda **kwargs: Mock(**kwargs),
                ):
            mock_tenant_config.get_app_config.side_effect = ["TestApp", "Test Description"]
            mock_tenant_config.get_context_policy.return_value = {}
            return await preparation_compiler.create_agent_config(
                agent_id=7,
                tenant_id="tenant_1",
                user_id="user_1",
                version_no=3,
                last_user_query=query,
                **overrides,
            )

    async def test_routing_enabled_selects_deep_model_for_analysis_query(self, monkeypatch):
        config = await self._run(
            monkeypatch,
            [_record(1, "qwen-fast", **QUICK_FACTS), _record(2, "deepseek-r1", **DEEP_FACTS)],
            query="请分析这个患者的鉴别诊断",
            routing_enabled=True,
        )
        # First-available would be model 1; routing must pick model 2.
        assert config.model_name == "deepseek-r1"

    async def test_routing_disabled_keeps_first_available(self, monkeypatch):
        config = await self._run(
            monkeypatch,
            [_record(1, "qwen-fast", **QUICK_FACTS), _record(2, "deepseek-r1", **DEEP_FACTS)],
            query="请分析这个患者的鉴别诊断",
            routing_enabled=False,
        )
        assert config.model_name == "qwen-fast"

    async def test_explicit_model_override_beats_routing(self, monkeypatch):
        config = await self._run(
            monkeypatch,
            [_record(1, "qwen-fast", **QUICK_FACTS), _record(2, "deepseek-r1", **DEEP_FACTS)],
            query="请分析这个患者的鉴别诊断",
            routing_enabled=True,
            override_model_id=1,
        )
        assert config.model_name == "qwen-fast"

    async def test_history_and_attachments_reach_classifier(self, monkeypatch):
        records = [
            _record(1, "qwen-fast", **QUICK_FACTS),
            _record(2, "long-model", **LONG_FACTS),
        ]
        config_light = await self._run(
            monkeypatch, records,
            query="hello", routing_enabled=True,
            run_history_length=0, run_has_attachments=False,
        )
        assert config_light.model_name == "qwen-fast"

        config_heavy = await self._run(
            monkeypatch, records,
            query="hello", routing_enabled=True,
            run_history_length=200, run_has_attachments=True,
        )
        # 200 history turns * 200 tokens + attachment overhead pushes the
        # estimate past the long-context threshold from the shipped rules.
        assert config_heavy.model_name == "long-model"

    async def test_no_capable_candidate_keeps_first_available(self, monkeypatch):
        config = await self._run(
            monkeypatch,
            [_record(1, "qwen-fast", **QUICK_FACTS)],
            query="请分析这个患者的鉴别诊断",
            routing_enabled=True,
        )
        assert config.model_name == "qwen-fast"

    async def test_unavailable_models_are_not_candidates(self, monkeypatch):
        config = await self._run(
            monkeypatch,
            [
                _record(1, "qwen-fast", **QUICK_FACTS),
                _record(2, "deepseek-r1", **DEEP_FACTS, connect_status="unavailable"),
            ],
            query="请分析这个患者的鉴别诊断",
            routing_enabled=True,
        )
        # Model 2 matches the tier but is unavailable; routing falls back
        # and model 1 (the only available candidate) serves the run.
        assert config.model_name == "qwen-fast"
