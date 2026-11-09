# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import unittest
from unittest.mock import patch

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException


class TestExtractJsonObject(unittest.TestCase):
    """Tests for _extract_json_object helper."""

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
    """Tests for generate_guardrail_rules_impl."""

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


class TestExtractJsonObjectEdgeCases(unittest.TestCase):
    """Additional edge case for _extract_json_object final fallback."""

    def test_utterly_broken_json_all_fallbacks_fail(self):
        """When all JSON repair strategies fail, return None."""
        from management.services.agent.prompt_generation import _extract_json_object
        # Snippet with unbalanced braces that confuses all three strategies
        raw = '{\\x not valid json ever }'
        result = _extract_json_object(raw)
        # All fallbacks fail - returns None
        self.assertIsNone(result)
