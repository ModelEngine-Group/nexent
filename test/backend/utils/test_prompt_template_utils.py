import pytest
from jinja2 import Environment, meta
from utils.prompt_template_utils import (
    get_prompt_generate_template_keys,
    get_nl2skill_prompt_template,
    merge_prompt_generate_templates,
    normalize_prompt_generate_template_content,
)


class TestPromptTemplateUtils:
    """Test cases for prompt_template_utils module"""

    def test_get_prompt_generate_template_keys_returns_an_independent_list(self):
        template_keys = get_prompt_generate_template_keys()

        assert "duty_system_prompt" in template_keys
        template_keys.clear()
        assert get_prompt_generate_template_keys()

    @pytest.mark.parametrize("template_content", [None, [], "invalid"])
    def test_normalize_prompt_generate_template_content_rejects_non_mappings(
        self, template_content
    ):
        assert normalize_prompt_generate_template_content(template_content) == {}

    def test_normalize_prompt_generate_template_content_supports_aliases(self):
        template_content = {
            "duty_system_prompt": "Current duty prompt",
            "DUTY_SYSTEM_PROMPT": "Legacy duty prompt",
            "CONSTRAINT_SYSTEM_PROMPT": "Legacy constraint prompt",
            "few_shots_system_prompt": "   ",
            "AGENT_VARIABLE_NAME_SYSTEM_PROMPT": 42,
        }

        assert normalize_prompt_generate_template_content(template_content) == {
            "duty_system_prompt": "Current duty prompt",
            "constraint_system_prompt": "Legacy constraint prompt",
        }

    def test_merge_prompt_generate_templates_uses_first_valid_value(self):
        merged = merge_prompt_generate_templates(
            None,
            {
                "duty_system_prompt": "Primary duty prompt",
                "constraint_system_prompt": "",
            },
            {
                "DUTY_SYSTEM_PROMPT": "Fallback duty prompt",
                "CONSTRAINT_SYSTEM_PROMPT": "Fallback constraint prompt",
                "USER_PROMPT": "Fallback user prompt",
            },
        )

        assert merged == {
            "duty_system_prompt": "Primary duty prompt",
            "constraint_system_prompt": "Fallback constraint prompt",
            "user_prompt": "Fallback user prompt",
        }

    @pytest.mark.parametrize("language", ["zh", "en"])
    def test_nl2agent_prompt_templates_define_runtime_variables(self, language):
        """Direct SDK resources expose the same runtime variables."""
        from nexent.core.prompts import load_prompt

        template_config = load_prompt(language, "meta/nl2agent")
        assert set(template_config) == {"system_prompt"}
        parsed_template = Environment().parse(template_config["system_prompt"])
        assert meta.find_undeclared_variables(parsed_template) == {
            "installed_tool_name", "recommend_tool_name", "save_tool_name",
            "max_results", "uninstalled_tool_name", "wrapper_name",
        }


class TestNl2SkillPromptTemplate:
    """Skill creation keeps its language and rendering behavior."""

    @pytest.mark.parametrize("language", ["zh", "en", "unknown"])
    def test_skill_template_uses_sdk_resource_and_language_fallback(self, language):
        result = get_nl2skill_prompt_template(
            language=language, user_request="Create a skill",
        )
        assert result["system_prompt"]
        assert result["user_prompt"]
        assert "{{" not in result["user_prompt"]

    def test_skill_template_missing_keys_fall_back_to_empty(self, mocker):
        mocker.patch(
            "utils.prompt_template_utils.load_prompt",
            return_value={"other": "data"},
        )
        result = get_nl2skill_prompt_template("zh")
        assert result == {"system_prompt": "", "user_prompt": ""}

    def test_skill_template_missing_resource_raises(self, mocker):
        mocker.patch(
            "utils.prompt_template_utils.load_prompt",
            side_effect=FileNotFoundError("File not found"),
        )
        with pytest.raises(FileNotFoundError):
            get_nl2skill_prompt_template("zh")


class TestNl2SkillPromptTemplateJinja:
    """Test cases for Jinja2 template rendering in get_nl2skill_prompt_template."""

    def test_jinja_rendering_without_existing_skill(self, mocker):
        """Test Jinja2 rendering with no existing_skill (should skip conditional blocks)"""
        mock_yaml_load = mocker.patch('yaml.safe_load')

        mock_yaml_load.return_value = {
            "system_prompt": "Hello {% if existing_skill %}{{ existing_skill.name }}{% else %}World{% endif %}",
            "user_prompt": "Request: test"
        }

        result = get_nl2skill_prompt_template(language='zh', existing_skill=None)

        assert result["system_prompt"] == "Hello World"
        assert result["user_prompt"] == "Request: test"

    def test_jinja_rendering_with_existing_skill(self, mocker):
        """Test Jinja2 rendering with existing_skill populates variables"""
        mock_yaml_load = mocker.patch('yaml.safe_load')

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

        result = get_nl2skill_prompt_template(language='zh', existing_skill=existing_skill)

        assert result["system_prompt"] == "Skill: my-test-skill, Desc: Test skill description, Tags: tag1, tag2"
        assert "my-test-skill" in result["system_prompt"]
        assert "Test skill description" in result["system_prompt"]
        assert "tag1" in result["system_prompt"]
        assert "tag2" in result["system_prompt"]

    def test_jinja_rendering_with_tags_array(self, mocker):
        """Test Jinja2 rendering with existing_skill tags as array"""
        mock_yaml_load = mocker.patch('yaml.safe_load')

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

        result = get_nl2skill_prompt_template(language='zh', existing_skill=existing_skill)

        assert "python" in result["system_prompt"]
        assert "backend" in result["system_prompt"]
        assert "api" in result["system_prompt"]

    def test_jinja_rendering_with_empty_tags(self, mocker):
        """Test Jinja2 rendering with existing_skill having empty tags"""
        mock_yaml_load = mocker.patch('yaml.safe_load')

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

        result = get_nl2skill_prompt_template(language='zh', existing_skill=existing_skill)

        assert "none" in result["system_prompt"]

    def test_jinja_rendering_user_prompt_with_existing_skill(self, mocker):
        """Test Jinja2 rendering of user_prompt with existing_skill"""
        mock_yaml_load = mocker.patch('yaml.safe_load')

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

        result = get_nl2skill_prompt_template(language='zh', existing_skill=existing_skill)

        assert "existing-skill-name" in result["user_prompt"]
        assert "Update" in result["user_prompt"]

    def test_jinja_rendering_conditional_blocks_uses_skill_content(self, mocker):
        """Test empty interactive drafts render as creation mode."""
        mock_yaml_load = mocker.patch('yaml.load')

        mock_yaml_load.return_value = {
            "system_prompt": "{% if has_existing_skill_content %}UPDATE{% else %}CREATE{% endif %} mode",
            "user_prompt": "{% if has_existing_skill_content %}Modify {{ existing_skill.name }}{% else %}Create new{% endif %}"
        }

        result_with_empty_snapshot = get_nl2skill_prompt_template(
            language='zh',
            existing_skill={"name": "", "description": "", "tags": [], "content": ""},
        )
        assert "CREATE" in result_with_empty_snapshot["system_prompt"]
        assert "UPDATE" not in result_with_empty_snapshot["system_prompt"]
        assert "Create new" in result_with_empty_snapshot["user_prompt"]
        assert "Modify" not in result_with_empty_snapshot["user_prompt"]

        result_with_skill = get_nl2skill_prompt_template(
            language='zh',
            existing_skill={"name": "test", "description": "desc", "tags": [], "content": "# Existing skill"},
        )
        assert "UPDATE" in result_with_skill["system_prompt"]
        assert "CREATE" not in result_with_skill["system_prompt"]
        assert "Modify test" in result_with_skill["user_prompt"]
        assert "Create new" not in result_with_skill["user_prompt"]

    def test_jinja_rendering_error_fallback(self, mocker):
        """Test Jinja2 rendering error falls back to raw content"""
        mock_yaml_load = mocker.patch('yaml.safe_load')

        mock_yaml_load.return_value = {
            "system_prompt": "Normal content",
            "user_prompt": "Also normal"
        }

        # Mock Template class from jinja2 module (imported inside the function)
        mock_template_class = mocker.patch('jinja2.Template')
        mock_template_class.side_effect = Exception("Jinja2 syntax error")

        existing_skill = {"name": "test", "description": "desc", "tags": [], "content": ""}
        result = get_nl2skill_prompt_template(language='zh', existing_skill=existing_skill)

        # Should return raw content when Jinja2 fails
        assert result["system_prompt"] == "Normal content"
        assert result["user_prompt"] == "Also normal"

    def test_jinja_rendering_complex_content(self, mocker):
        """Test Jinja2 rendering with complex skill content including special characters"""
        mock_yaml_load = mocker.patch('yaml.safe_load')

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

        result = get_nl2skill_prompt_template(language='zh', existing_skill=existing_skill)

        assert "# Title" in result["system_prompt"]
        assert "**markdown**" in result["system_prompt"]
        assert "`code`" in result["system_prompt"]

    def test_jinja_rendering_english_template(self, mocker):
        """Test Jinja2 rendering works with English template"""
        mock_yaml_load = mocker.patch('yaml.safe_load')

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

        result = get_nl2skill_prompt_template(language='en', existing_skill=existing_skill)

        assert "Updating" in result["system_prompt"]
        assert "english-skill-test" in result["user_prompt"]
