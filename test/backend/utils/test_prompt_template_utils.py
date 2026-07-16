import pytest
from unittest.mock import mock_open

from utils.prompt_template_utils import (
    get_agent_prompt_template,
    get_prompt_generate_prompt_template,
    get_prompt_optimize_prompt_template,
    get_generate_title_prompt_template,
    get_document_summary_prompt_template,
    get_cluster_summary_reduce_prompt_template,
    get_skill_creation_simple_prompt_template,
    get_nl2agent_system_prompt_template,
    get_nl2agent_system_prompt,
    get_nl2agent_seed_config,
    get_prompt_template,
)


class TestPromptTemplateUtils:
    """Test cases for prompt_template_utils module"""

    def test_get_agent_prompt_template_manager_zh(self, mocker):
        """Test get_agent_prompt_template for manager mode in Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"test": "data"}'))

        mock_yaml_load.return_value = {"test": "data"}
        result = get_agent_prompt_template(is_manager=True, language='zh')

        # Verify the function was called with correct parameters
        # The actual path will be an absolute path, so we check that it contains the expected relative path
        call_args = mock_file.call_args[0]
        assert 'backend/prompts/manager_system_prompt_template_zh.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'
        mock_yaml_load.assert_called_once()
        assert result == {"test": "data"}

    def test_get_agent_prompt_template_manager_en(self, mocker):
        """Test get_agent_prompt_template for manager mode in English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"test": "data"}'))

        mock_yaml_load.return_value = {"test": "data"}
        result = get_agent_prompt_template(is_manager=True, language='en')

        # Verify the function was called with correct parameters
        # The actual path will be an absolute path, so we check that it ends with the expected relative path
        call_args = mock_file.call_args[0]
        assert 'backend/prompts/manager_system_prompt_template_en.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'
        mock_yaml_load.assert_called_once()
        assert result == {"test": "data"}

    def test_get_agent_prompt_template_managed_zh(self, mocker):
        """Test get_agent_prompt_template for managed mode in Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"test": "data"}'))

        mock_yaml_load.return_value = {"test": "data"}
        result = get_agent_prompt_template(is_manager=False, language='zh')

        # Verify the function was called with correct parameters
        # The actual path will be an absolute path, so we check that it ends with the expected relative path
        call_args = mock_file.call_args[0]
        assert 'backend/prompts/managed_system_prompt_template_zh.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'
        mock_yaml_load.assert_called_once()
        assert result == {"test": "data"}

    def test_get_agent_prompt_template_managed_en(self, mocker):
        """Test get_agent_prompt_template for managed mode in English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"test": "data"}'))

        mock_yaml_load.return_value = {"test": "data"}
        result = get_agent_prompt_template(is_manager=False, language='en')

        # Verify the function was called with correct parameters
        # The actual path will be an absolute path, so we check that it ends with the expected relative path
        call_args = mock_file.call_args[0]
        assert 'backend/prompts/managed_system_prompt_template_en.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'
        mock_yaml_load.assert_called_once()
        assert result == {"test": "data"}

    def test_get_prompt_generate_prompt_template_zh(self, mocker):
        """Test get_prompt_generate_prompt_template for Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"test": "data"}'))

        mock_yaml_load.return_value = {"test": "data"}
        result = get_prompt_generate_prompt_template(language='zh')

        # Verify the function was called with correct parameters
        # The actual path will be an absolute path, so we check that it ends with the expected relative path
        call_args = mock_file.call_args[0]
        assert 'backend/prompts/utils/prompt_generate_zh.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'
        mock_yaml_load.assert_called_once()
        assert result == {"test": "data"}

    def test_get_prompt_generate_prompt_template_en(self, mocker):
        """Test get_prompt_generate_prompt_template for English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"test": "data"}'))

        mock_yaml_load.return_value = {"test": "data"}
        result = get_prompt_generate_prompt_template(language='en')

        # Verify the function was called with correct parameters
        # The actual path will be an absolute path, so we check that it ends with the expected relative path
        call_args = mock_file.call_args[0]
        assert 'backend/prompts/utils/prompt_generate_en.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'
        mock_yaml_load.assert_called_once()
        assert result == {"test": "data"}

    def test_get_prompt_generate_prompt_template_default_language(self, mocker):
        """Test get_prompt_generate_prompt_template with default language (should be Chinese)"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"test": "data"}'))

        mock_yaml_load.return_value = {"test": "data"}
        result = get_prompt_generate_prompt_template()

        # Verify the function was called with correct parameters
        # The actual path will be an absolute path, so we check that it ends with the expected relative path
        call_args = mock_file.call_args[0]
        assert 'backend/prompts/utils/prompt_generate_zh.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'
        mock_yaml_load.assert_called_once()
        assert result == {"test": "data"}

    def test_get_prompt_optimize_prompt_template_en(self, mocker):
        """Test get_prompt_optimize_prompt_template for English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"test": "data"}'))

        mock_yaml_load.return_value = {"test": "data"}
        result = get_prompt_optimize_prompt_template(language='en')

        call_args = mock_file.call_args[0]
        assert 'backend/prompts/utils/prompt_optimize_en.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'
        mock_yaml_load.assert_called_once()
        assert result == {"test": "data"}

    def test_get_nl2agent_system_prompt_template_zh(self, mocker):
        """Test get_nl2agent_system_prompt_template for Chinese."""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system_prompt: "builder"'))

        mock_yaml_load.return_value = {"system_prompt": "builder"}
        result = get_nl2agent_system_prompt_template(language='zh')

        call_args = mock_file.call_args[0]
        assert 'backend/prompts/nl2agent_system_prompt_zh.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'
        mock_yaml_load.assert_called_once()
        assert result == {"system_prompt": "builder"}

    def test_get_nl2agent_system_prompt_template_en(self, mocker):
        """Test get_nl2agent_system_prompt_template for English."""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system_prompt: "builder"'))

        mock_yaml_load.return_value = {"system_prompt": "builder"}
        result = get_nl2agent_system_prompt_template(language='en')

        call_args = mock_file.call_args[0]
        assert 'backend/prompts/nl2agent_system_prompt_en.yaml' in call_args[0].replace('\\', '/')
        assert call_args[1] == 'r'
        assert mock_file.call_args[1]['encoding'] == 'utf-8'
        mock_yaml_load.assert_called_once()
        assert result == {"system_prompt": "builder"}

    def test_get_nl2agent_system_prompt_returns_runtime_prompt(self, mocker):
        """Test NL2AGENT runtime prompt extraction."""
        mocker.patch(
            'utils.prompt_template_utils.get_nl2agent_system_prompt_template',
            return_value={"system_prompt": "  runtime builder prompt  "},
        )

        result = get_nl2agent_system_prompt(language='en')

        assert result == "  runtime builder prompt  "

    @pytest.mark.parametrize("language", ["en", "zh"])
    def test_nl2agent_prompt_consumes_authoritative_workflow_summary(
        self, language
    ):
        """The prompt selects actions from the shared evaluator summary."""
        prompt = get_nl2agent_system_prompt(language=language)

        for field in (
            "current_stage",
            "expected_card_types",
            "allowed_actions",
            "draft_agent_id",
        ):
            assert field in prompt
        assert "model_selection_confirmed=false" not in prompt
        assert "mcp_batch_registered=false" not in prompt
        assert "[[NL2AGENT_AUTO_CONTINUE]]" in prompt
        assert "[[NL2AGENT_CARD_RETRY]]" in prompt

    @pytest.mark.parametrize("language", ["en", "zh"])
    def test_nl2agent_prompt_limits_execution_to_three_search_tools(
        self, language
    ):
        """Skills and cards must never be treated as callable tools."""
        prompt = get_nl2agent_system_prompt(language=language)

        assert "<code>" in prompt
        for tool_name in (
            "nl2agent_search_local_resources",
            "nl2agent_search_web_mcps",
            "nl2agent_search_web_skills",
        ):
            assert tool_name in prompt
        assert "nl2agent_finalize_proposal" not in prompt
        assert "nl2agent-search-" not in prompt
        assert "print(result)" in prompt
        assert "print(mcp_result)" in prompt
        assert "print(skill_result)" in prompt

    @pytest.mark.parametrize("language", ["en", "zh"])
    def test_nl2agent_prompt_preserves_fresh_observations_as_cards(
        self, language
    ):
        prompt = get_nl2agent_system_prompt(language=language)

        assert "Observation" in prompt
        assert "recommendation_batch_id" in prompt
        assert "nl2agent-local-resources" in prompt
        assert "nl2agent-web-mcps" in prompt
        assert "nl2agent-web-skills" in prompt
        assert "Do not reconstruct" in prompt or "不得重建" in prompt
        assert "Do not loop over keywords" in prompt or "不得逐关键词循环" in prompt

    @pytest.mark.parametrize("language", ["en", "zh"])
    def test_nl2agent_prompt_keeps_requirements_and_model_gates(
        self, language
    ):
        prompt = get_nl2agent_system_prompt(language=language)

        for stage in (
            "requirements_collecting",
            "requirements_confirmation",
            "model_selection",
        ):
            assert stage in prompt
        for field in (
            "goal",
            "audience_or_scenario",
            "primary_input",
            "expected_output",
            "key_constraints",
        ):
            assert field in prompt
        assert "nl2agent-requirements-summary" in prompt
        assert "nl2agent-model-selection" in prompt
        assert (
            "Never name, recommend, compare, rank, or invent an LLM" in prompt
            or "不得说出、推荐、比较、排序或编造任何 LLM" in prompt
        )

    @pytest.mark.parametrize(
        ("language", "collecting_gate", "default_gate", "missing_fact_gate"),
        [
            (
                "en",
                "during `requirements_collecting`, generate only a `requirements_summary`, and only when "
                "`render_requirements_summary` is allowed and all five facts are explicitly available",
                "In every other stage, generate only card types listed in `expected_card_types`",
                "If any fact is missing, ask one focused question for the first missing fact and do not output a card",
            ),
            (
                "zh",
                "在 `requirements_collecting` 阶段，只有当 `render_requirements_summary` 被允许且五项事实均已明确提供时，"
                "才能生成 `requirements_summary`",
                "其他所有阶段只生成 `expected_card_types` 中列出的卡片",
                "任一事实缺失时，只询问第一个缺失项，不得输出卡片",
            ),
        ],
    )
    def test_nl2agent_prompt_has_unambiguous_requirements_card_gate(
        self, language, collecting_gate, default_gate, missing_fact_gate
    ):
        """Requirements collection is the explicit exception to expected card types."""
        prompt = get_nl2agent_system_prompt(language=language)

        assert collecting_gate in prompt
        assert default_gate in prompt
        assert missing_fact_gate in prompt
        assert "\n3. Generate only card types listed in `expected_card_types`." not in prompt
        assert "\n3. 只生成 `expected_card_types` 中列出的卡片。" not in prompt

    @pytest.mark.parametrize("language", ["en", "zh"])
    def test_nl2agent_prompt_generates_identity_and_direct_final_card(
        self, language
    ):
        prompt = get_nl2agent_system_prompt(language=language)

        assert "agent_identity" in prompt
        assert "final_review" in prompt
        assert "display_name" in prompt
        assert "nl2agent-agent-identity" in prompt
        assert "nl2agent-finalize" in prompt
        for required_field in (
            "business_description",
            "duty_prompt",
            "greeting_message",
        ):
            assert required_field in prompt
        for forbidden_field in (
            '"business_logic_model_id"',
            '"selected_tools"',
            '"selected_skills"',
            '"sub_agent_ids"',
        ):
            assert forbidden_field not in prompt

    @pytest.mark.parametrize("language", ["en", "zh"])
    def test_nl2agent_prompt_collects_mcp_configuration_only_in_card(
        self, language
    ):
        prompt = get_nl2agent_system_prompt(language=language)

        assert "MCP card" in prompt or "MCP 卡片" in prompt
        assert "Never ask for them in chat" in prompt or "不得在聊天中询问" in prompt
        assert "secret" in prompt.lower()
        assert "ask one focused question at a time for required non-secret" not in prompt.lower()


    def test_get_nl2agent_seed_config_normalizes_metadata(self, mocker):
        """Test NL2AGENT seed metadata extraction from the richer YAML shape."""
        mocker.patch(
            'utils.prompt_template_utils.get_nl2agent_system_prompt_template',
            return_value={
                "agent_info": {
                    "name": "nl2agent",
                    "display_name": " Agent Builder ",
                    "description": "Builds agents",
                    "ignored": "value",
                },
                "prompt_segments": {
                    "duty_prompt": "Build agents",
                    "constraint_prompt": "Confirm first",
                    "few_shots_prompt": "   ",
                },
                "system_prompt": " Runtime prompt ",
            },
        )

        result = get_nl2agent_seed_config(language='en')

        assert result == {
            "agent_info": {
                "name": "nl2agent",
                "display_name": "Agent Builder",
                "description": "Builds agents",
            },
            "prompt_segments": {
                "duty_prompt": "Build agents",
                "constraint_prompt": "Confirm first",
            },
            "system_prompt": "Runtime prompt",
        }


class TestGetPromptTemplate:
    """Test cases for get_prompt_template function"""

    def test_get_prompt_template_unsupported_type(self, mocker):
        """Test get_prompt_template with unsupported template type raises ValueError"""
        with pytest.raises(ValueError) as excinfo:
            get_prompt_template(template_type='unsupported_type', language='zh')

        assert "Unsupported template type" in str(excinfo.value)

    def test_get_prompt_template_file_not_found(self, mocker):
        """Test get_prompt_template raises FileNotFoundError when file is missing"""
        mocker.patch('builtins.open', side_effect=FileNotFoundError("File not found"))

        with pytest.raises(FileNotFoundError):
            get_prompt_template(template_type='prompt_generate', language='zh')

    def test_get_prompt_template_prompt_generate_zh(self, mocker):
        """Test get_prompt_template for prompt_generate in Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system: "test"'))

        mock_yaml_load.return_value = {"system": "test"}
        result = get_prompt_template(template_type='prompt_generate', language='zh')

        call_args = mock_file.call_args[0]
        assert 'utils/prompt_generate_zh.yaml' in call_args[0].replace('\\', '/')
        mock_yaml_load.assert_called_once()
        assert result == {"system": "test"}

    def test_get_prompt_template_prompt_generate_en(self, mocker):
        """Test get_prompt_template for prompt_generate in English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system: "test"'))

        mock_yaml_load.return_value = {"system": "test"}
        result = get_prompt_template(template_type='prompt_generate', language='en')

        call_args = mock_file.call_args[0]
        assert 'utils/prompt_generate_en.yaml' in call_args[0].replace('\\', '/')
        assert result == {"system": "test"}

    def test_get_prompt_template_agent_manager_zh(self, mocker):
        """Test get_prompt_template for agent with is_manager=True in Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system: "manager"'))

        mock_yaml_load.return_value = {"system": "manager"}
        result = get_prompt_template(template_type='agent', language='zh', is_manager=True)

        call_args = mock_file.call_args[0]
        assert 'manager_system_prompt_template_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"system": "manager"}

    def test_get_prompt_template_agent_managed_zh(self, mocker):
        """Test get_prompt_template for agent with is_manager=False in Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system: "managed"'))

        mock_yaml_load.return_value = {"system": "managed"}
        result = get_prompt_template(template_type='agent', language='zh', is_manager=False)

        call_args = mock_file.call_args[0]
        assert 'managed_system_prompt_template_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"system": "managed"}

    def test_get_prompt_template_generate_title_zh(self, mocker):
        """Test get_prompt_template for generate_title in Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='title: "test"'))

        mock_yaml_load.return_value = {"title": "test"}
        result = get_prompt_template(template_type='generate_title', language='zh')

        call_args = mock_file.call_args[0]
        assert 'utils/generate_title_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"title": "test"}

    def test_get_prompt_template_generate_title_en(self, mocker):
        """Test get_prompt_template for generate_title in English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='title: "test"'))

        mock_yaml_load.return_value = {"title": "test"}
        result = get_prompt_template(template_type='generate_title', language='en')

        call_args = mock_file.call_args[0]
        assert 'utils/generate_title_en.yaml' in call_args[0].replace('\\', '/')
        assert result == {"title": "test"}

    def test_get_prompt_template_document_summary_zh(self, mocker):
        """Test get_prompt_template for document_summary in Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='summary: "test"'))

        mock_yaml_load.return_value = {"summary": "test"}
        result = get_prompt_template(template_type='document_summary', language='zh')

        call_args = mock_file.call_args[0]
        assert 'document_summary_agent_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"summary": "test"}

    def test_get_prompt_template_document_summary_en(self, mocker):
        """Test get_prompt_template for document_summary in English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='summary: "test"'))

        mock_yaml_load.return_value = {"summary": "test"}
        result = get_prompt_template(template_type='document_summary', language='en')

        call_args = mock_file.call_args[0]
        assert 'document_summary_agent_en.yaml' in call_args[0].replace('\\', '/')
        assert result == {"summary": "test"}

    def test_get_prompt_template_cluster_summary_reduce_zh(self, mocker):
        """Test get_prompt_template for cluster_summary_reduce in Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='reduce: "test"'))

        mock_yaml_load.return_value = {"reduce": "test"}
        result = get_prompt_template(template_type='cluster_summary_reduce', language='zh')

        call_args = mock_file.call_args[0]
        assert 'cluster_summary_reduce_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"reduce": "test"}

    def test_get_prompt_template_cluster_summary_reduce_en(self, mocker):
        """Test get_prompt_template for cluster_summary_reduce in English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='reduce: "test"'))

        mock_yaml_load.return_value = {"reduce": "test"}
        result = get_prompt_template(template_type='cluster_summary_reduce', language='en')

        call_args = mock_file.call_args[0]
        assert 'cluster_summary_reduce_en.yaml' in call_args[0].replace('\\', '/')
        assert result == {"reduce": "test"}


class TestWrapperFunctions:
    """Test cases for wrapper functions"""

    def test_get_generate_title_prompt_template_zh(self, mocker):
        """Test get_generate_title_prompt_template for Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"title": "test"}'))

        mock_yaml_load.return_value = {"title": "test"}
        result = get_generate_title_prompt_template(language='zh')

        call_args = mock_file.call_args[0]
        assert 'utils/generate_title_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"title": "test"}

    def test_get_generate_title_prompt_template_en(self, mocker):
        """Test get_generate_title_prompt_template for English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"title": "test"}'))

        mock_yaml_load.return_value = {"title": "test"}
        result = get_generate_title_prompt_template(language='en')

        call_args = mock_file.call_args[0]
        assert 'utils/generate_title_en.yaml' in call_args[0].replace('\\', '/')
        assert result == {"title": "test"}

    def test_get_generate_title_prompt_template_default(self, mocker):
        """Test get_generate_title_prompt_template with default language"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"title": "test"}'))

        mock_yaml_load.return_value = {"title": "test"}
        result = get_generate_title_prompt_template()

        call_args = mock_file.call_args[0]
        assert 'utils/generate_title_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"title": "test"}

    def test_get_document_summary_prompt_template_zh(self, mocker):
        """Test get_document_summary_prompt_template for Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"summary": "test"}'))

        mock_yaml_load.return_value = {"summary": "test"}
        result = get_document_summary_prompt_template(language='zh')

        call_args = mock_file.call_args[0]
        assert 'document_summary_agent_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"summary": "test"}

    def test_get_document_summary_prompt_template_en(self, mocker):
        """Test get_document_summary_prompt_template for English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"summary": "test"}'))

        mock_yaml_load.return_value = {"summary": "test"}
        result = get_document_summary_prompt_template(language='en')

        call_args = mock_file.call_args[0]
        assert 'document_summary_agent_en.yaml' in call_args[0].replace('\\', '/')
        assert result == {"summary": "test"}

    def test_get_document_summary_prompt_template_default(self, mocker):
        """Test get_document_summary_prompt_template with default language"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"summary": "test"}'))

        mock_yaml_load.return_value = {"summary": "test"}
        result = get_document_summary_prompt_template()

        call_args = mock_file.call_args[0]
        assert 'document_summary_agent_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"summary": "test"}

    def test_get_cluster_summary_reduce_prompt_template_zh(self, mocker):
        """Test get_cluster_summary_reduce_prompt_template for Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"reduce": "test"}'))

        mock_yaml_load.return_value = {"reduce": "test"}
        result = get_cluster_summary_reduce_prompt_template(language='zh')

        call_args = mock_file.call_args[0]
        assert 'cluster_summary_reduce_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"reduce": "test"}

    def test_get_cluster_summary_reduce_prompt_template_en(self, mocker):
        """Test get_cluster_summary_reduce_prompt_template for English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"reduce": "test"}'))

        mock_yaml_load.return_value = {"reduce": "test"}
        result = get_cluster_summary_reduce_prompt_template(language='en')

        call_args = mock_file.call_args[0]
        assert 'cluster_summary_reduce_en.yaml' in call_args[0].replace('\\', '/')
        assert result == {"reduce": "test"}

    def test_get_cluster_summary_reduce_prompt_template_default(self, mocker):
        """Test get_cluster_summary_reduce_prompt_template with default language"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='{"reduce": "test"}'))

        mock_yaml_load.return_value = {"reduce": "test"}
        result = get_cluster_summary_reduce_prompt_template()

        call_args = mock_file.call_args[0]
        assert 'cluster_summary_reduce_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"reduce": "test"}


class TestSkillCreationSimplePromptTemplate:
    """Test cases for get_skill_creation_simple_prompt_template function"""

    def test_get_skill_creation_simple_prompt_template_zh(self, mocker):
        """Test get_skill_creation_simple_prompt_template for Chinese"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system_prompt: "sys"\nuser_prompt: "user"'))

        mock_yaml_load.return_value = {"system_prompt": "sys", "user_prompt": "user"}
        result = get_skill_creation_simple_prompt_template(language='zh')

        call_args = mock_file.call_args[0]
        assert 'skill_creation_simple_zh.yaml' in call_args[0].replace('\\', '/')
        mock_yaml_load.assert_called_once()
        assert result == {"system_prompt": "sys", "user_prompt": "user"}

    def test_get_skill_creation_simple_prompt_template_en(self, mocker):
        """Test get_skill_creation_simple_prompt_template for English"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system_prompt: "sys"\nuser_prompt: "user"'))

        mock_yaml_load.return_value = {"system_prompt": "sys", "user_prompt": "user"}
        result = get_skill_creation_simple_prompt_template(language='en')

        call_args = mock_file.call_args[0]
        assert 'skill_creation_simple_en.yaml' in call_args[0].replace('\\', '/')
        assert result == {"system_prompt": "sys", "user_prompt": "user"}

    def test_get_skill_creation_simple_prompt_template_default(self, mocker):
        """Test get_skill_creation_simple_prompt_template with default language"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system_prompt: "sys"\nuser_prompt: "user"'))

        mock_yaml_load.return_value = {"system_prompt": "sys", "user_prompt": "user"}
        result = get_skill_creation_simple_prompt_template()

        call_args = mock_file.call_args[0]
        assert 'skill_creation_simple_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"system_prompt": "sys", "user_prompt": "user"}

    def test_get_skill_creation_simple_prompt_template_fallback(self, mocker):
        """Test get_skill_creation_simple_prompt_template falls back to Chinese for unknown language"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='system_prompt: "sys"\nuser_prompt: "user"'))

        mock_yaml_load.return_value = {"system_prompt": "sys", "user_prompt": "user"}
        result = get_skill_creation_simple_prompt_template(language='unknown')

        call_args = mock_file.call_args[0]
        assert 'skill_creation_simple_zh.yaml' in call_args[0].replace('\\', '/')
        assert result == {"system_prompt": "sys", "user_prompt": "user"}

    def test_get_skill_creation_simple_prompt_template_missing_keys(self, mocker):
        """Test get_skill_creation_simple_prompt_template handles missing keys in YAML"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(read_data='other: "data"'))

        mock_yaml_load.return_value = {"other": "data"}
        result = get_skill_creation_simple_prompt_template(language='zh')

        # Missing keys should default to empty strings
        assert result == {"system_prompt": "", "user_prompt": ""}

    def test_get_skill_creation_simple_prompt_template_file_not_found(self, mocker):
        """Test get_skill_creation_simple_prompt_template raises FileNotFoundError when file is missing"""
        mocker.patch('builtins.open', side_effect=FileNotFoundError("File not found"))

        with pytest.raises(FileNotFoundError):
            get_skill_creation_simple_prompt_template(language='zh')


class TestSkillCreationSimplePromptTemplateJinja:
    """Test cases for Jinja2 template rendering in get_skill_creation_simple_prompt_template"""

    def test_jinja_rendering_without_existing_skill(self, mocker):
        """Test Jinja2 rendering with no existing_skill (should skip conditional blocks)"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(
            read_data='system_prompt: "Hello {% if existing_skill %}{{ existing_skill.name }}{% else %}World{% endif %}"\n'
                     'user_prompt: "Request: test"'
        ))

        mock_yaml_load.return_value = {
            "system_prompt": "Hello {% if existing_skill %}{{ existing_skill.name }}{% else %}World{% endif %}",
            "user_prompt": "Request: test"
        }

        result = get_skill_creation_simple_prompt_template(language='zh', existing_skill=None)

        assert result["system_prompt"] == "Hello World"
        assert result["user_prompt"] == "Request: test"

    def test_jinja_rendering_with_existing_skill(self, mocker):
        """Test Jinja2 rendering with existing_skill populates variables"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(
            read_data='system_prompt: "Skill: {{ existing_skill.name }}, Desc: {{ existing_skill.description }}, Tags: {{ existing_skill.tags | join(\', \') }}"'
        ))

        mock_yaml_load.return_value = {
            "system_prompt": "Skill: {{ existing_skill.name }}, Desc: {{ existing_skill.description }}, Tags: {{ existing_skill.tags | join(', ') }}",
            "user_prompt": "Update prompt"
        }

        existing_skill = {
            "name": "my-test-skill",
            "description": "Test skill description",
            "tags": ["tag1", "tag2"],
            "content": "# Test Content"
        }

        result = get_skill_creation_simple_prompt_template(language='zh', existing_skill=existing_skill)

        assert result["system_prompt"] == "Skill: my-test-skill, Desc: Test skill description, Tags: tag1, tag2"
        assert "my-test-skill" in result["system_prompt"]
        assert "Test skill description" in result["system_prompt"]
        assert "tag1" in result["system_prompt"]
        assert "tag2" in result["system_prompt"]

    def test_jinja_rendering_with_tags_array(self, mocker):
        """Test Jinja2 rendering with existing_skill tags as array"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(
            read_data='system_prompt: "Tags: {{ existing_skill.tags | join(\', \') }}"'
        ))

        mock_yaml_load.return_value = {
            "system_prompt": "Tags: {{ existing_skill.tags | join(', ') }}",
            "user_prompt": ""
        }

        existing_skill = {
            "name": "skill-with-tags",
            "description": "A skill with multiple tags",
            "tags": ["python", "backend", "api"],
            "content": "Content here"
        }

        result = get_skill_creation_simple_prompt_template(language='zh', existing_skill=existing_skill)

        assert "python" in result["system_prompt"]
        assert "backend" in result["system_prompt"]
        assert "api" in result["system_prompt"]

    def test_jinja_rendering_with_empty_tags(self, mocker):
        """Test Jinja2 rendering with existing_skill having empty tags"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(
            read_data='system_prompt: "Tags: {{ existing_skill.tags | join(\', \') if existing_skill.tags else \'none\' }}"'
        ))

        mock_yaml_load.return_value = {
            "system_prompt": "Tags: {{ existing_skill.tags | join(', ') if existing_skill.tags else 'none' }}",
            "user_prompt": ""
        }

        existing_skill = {
            "name": "skill-no-tags",
            "description": "A skill without tags",
            "tags": [],
            "content": "Content here"
        }

        result = get_skill_creation_simple_prompt_template(language='zh', existing_skill=existing_skill)

        assert "none" in result["system_prompt"]

    def test_jinja_rendering_user_prompt_with_existing_skill(self, mocker):
        """Test Jinja2 rendering of user_prompt with existing_skill"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(
            read_data='system_prompt: "System prompt"\nuser_prompt: "Update {{ existing_skill.name }} with new requirements"'
        ))

        mock_yaml_load.return_value = {
            "system_prompt": "System prompt",
            "user_prompt": "Update {{ existing_skill.name }} with new requirements"
        }

        existing_skill = {
            "name": "existing-skill-name",
            "description": "Description",
            "tags": ["test"],
            "content": "Old content"
        }

        result = get_skill_creation_simple_prompt_template(language='zh', existing_skill=existing_skill)

        assert "existing-skill-name" in result["user_prompt"]
        assert "Update" in result["user_prompt"]

    def test_jinja_rendering_conditional_blocks(self, mocker):
        """Test Jinja2 conditional blocks are properly handled"""
        mock_yaml_load = mocker.patch('yaml.load')
        mock_file = mocker.patch('builtins.open', mock_open(
            read_data='system_prompt: "{% if existing_skill %}UPDATE{% else %}CREATE{% endif %} mode"\n'
                     'user_prompt: "{% if existing_skill %}Modify {{ existing_skill.name }}{% else %}Create new{% endif %}"'
        ))

        mock_yaml_load.return_value = {
            "system_prompt": "{% if existing_skill %}UPDATE{% else %}CREATE{% endif %} mode",
            "user_prompt": "{% if existing_skill %}Modify {{ existing_skill.name }}{% else %}Create new{% endif %}"
        }

        # Test with existing_skill
        result_with_skill = get_skill_creation_simple_prompt_template(
            language='zh',
            existing_skill={"name": "test", "description": "desc", "tags": [], "content": ""}
        )
        assert "UPDATE" in result_with_skill["system_prompt"]
        assert "CREATE" not in result_with_skill["system_prompt"]
        assert "Modify test" in result_with_skill["user_prompt"]
        assert "Create new" not in result_with_skill["user_prompt"]

        # Test without existing_skill
        result_without_skill = get_skill_creation_simple_prompt_template(language='zh', existing_skill=None)
        assert "CREATE" in result_without_skill["system_prompt"]
        assert "UPDATE" not in result_without_skill["system_prompt"]
        assert "Create new" in result_without_skill["user_prompt"]
        assert "Modify" not in result_without_skill["user_prompt"]

    def test_jinja_rendering_error_fallback(self, mocker):
        """Test Jinja2 rendering error falls back to raw content"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(
            read_data='system_prompt: "Normal content"\nuser_prompt: "Also normal"'
        ))

        mock_yaml_load.return_value = {
            "system_prompt": "Normal content",
            "user_prompt": "Also normal"
        }

        # Mock Template class from jinja2 module (imported inside the function)
        mock_template_class = mocker.patch('jinja2.Template')
        mock_template_class.side_effect = Exception("Jinja2 syntax error")

        existing_skill = {"name": "test", "description": "desc", "tags": [], "content": ""}
        result = get_skill_creation_simple_prompt_template(language='zh', existing_skill=existing_skill)

        # Should return raw content when Jinja2 fails
        assert result["system_prompt"] == "Normal content"
        assert result["user_prompt"] == "Also normal"

    def test_jinja_rendering_complex_content(self, mocker):
        """Test Jinja2 rendering with complex skill content including special characters"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(
            read_data='system_prompt: "{{ existing_skill.content }}"'
        ))

        mock_yaml_load.return_value = {
            "system_prompt": "{{ existing_skill.content }}",
            "user_prompt": ""
        }

        existing_skill = {
            "name": "complex-skill",
            "description": "A skill with complex content",
            "tags": ["special"],
            "content": "# Title\n\nSome content with **markdown** and `code`"
        }

        result = get_skill_creation_simple_prompt_template(language='zh', existing_skill=existing_skill)

        assert "# Title" in result["system_prompt"]
        assert "**markdown**" in result["system_prompt"]
        assert "`code`" in result["system_prompt"]

    def test_jinja_rendering_english_template(self, mocker):
        """Test Jinja2 rendering works with English template"""
        mock_yaml_load = mocker.patch('yaml.safe_load')
        mock_file = mocker.patch('builtins.open', mock_open(
            read_data='system_prompt: "{% if existing_skill %}Updating{% else %}Creating{% endif %} a skill"\n'
                     'user_prompt: "Skill: {{ existing_skill.name if existing_skill else \'new\' }}"'
        ))

        mock_yaml_load.return_value = {
            "system_prompt": "{% if existing_skill %}Updating{% else %}Creating{% endif %} a skill",
            "user_prompt": "Skill: {{ existing_skill.name if existing_skill else 'new' }}"
        }

        existing_skill = {
            "name": "english-skill-test",
            "description": "English skill description",
            "tags": ["en", "test"],
            "content": "English content"
        }

        result = get_skill_creation_simple_prompt_template(language='en', existing_skill=existing_skill)

        assert "Updating" in result["system_prompt"]
        assert "english-skill-test" in result["user_prompt"]
