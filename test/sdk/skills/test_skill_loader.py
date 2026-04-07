"""
Unit tests for nexent.skills.skill_loader module.
"""
import sys
import os
import importlib.util

import pytest

# Load skill_loader module directly without nexent package imports
spec = importlib.util.spec_from_file_location(
    "skill_loader",
    os.path.join(os.path.dirname(__file__), "../../../sdk/nexent/skills/skill_loader.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SkillLoader = module.SkillLoader


class TestSkillLoaderParse:
    """Test SkillLoader.parse method."""

    def test_parse_basic_frontmatter(self):
        """Test parsing basic SKILL.md with required fields."""
        content = """---
name: test-skill
description: A test skill
---
# Content
"""
        result = SkillLoader.parse(content)
        assert result["name"] == "test-skill"
        assert result["description"] == "A test skill"
        assert result["allowed_tools"] == []
        assert result["tags"] == []
        assert result["content"] == "# Content"

    def test_parse_with_allowed_tools(self):
        """Test parsing with allowed-tools field."""
        content = """---
name: tool-skill
description: A tool skill
allowed-tools:
  - tool1
  - tool2
---
# Body
"""
        result = SkillLoader.parse(content)
        assert result["name"] == "tool-skill"
        assert result["allowed_tools"] == ["tool1", "tool2"]

    def test_parse_with_tags(self):
        """Test parsing with tags field."""
        content = """---
name: tagged-skill
description: A tagged skill
tags:
  - python
  - ml
---
# Body
"""
        result = SkillLoader.parse(content)
        assert result["name"] == "tagged-skill"
        assert result["tags"] == ["python", "ml"]

    def test_parse_ignores_unknown_fields(self):
        """Test that unknown fields are ignored during parsing."""
        content = """---
name: minimax-docx
author: MiniMaxAI
version: 1.0
license: MIT
description: Process DOCX files
---
# Content
"""
        result = SkillLoader.parse(content)
        assert result["name"] == "minimax-docx"
        assert result["description"] == "Process DOCX files"
        # author, version, license should be ignored

    def test_parse_missing_frontmatter_raises(self):
        """Test that missing frontmatter raises ValueError."""
        content = "# Just content\nNo frontmatter"
        with pytest.raises(ValueError, match="YAML frontmatter"):
            SkillLoader.parse(content)

    def test_parse_missing_name_raises(self):
        """Test that missing name field raises ValueError."""
        content = """---
description: No name here
---
# Content
"""
        with pytest.raises(ValueError, match="'name' field"):
            SkillLoader.parse(content)

    def test_parse_missing_description_raises(self):
        """Test that missing description field raises ValueError."""
        content = """---
name: no-desc
---
# Content
"""
        with pytest.raises(ValueError, match="'description' field"):
            SkillLoader.parse(content)

    def test_parse_with_source_path(self):
        """Test that source_path is set correctly."""
        content = """---
name: path-test
description: Test source path
---
# Body
"""
        result = SkillLoader.parse(content, source_path="/path/to/SKILL.md")
        assert result["source_path"] == "/path/to/SKILL.md"


class TestSkillLoaderFixYamlFrontmatter:
    """Test SkillLoader._fix_yaml_frontmatter method."""

    def test_fix_value_with_colon(self):
        """Test fixing values that contain colons."""
        frontmatter = """name: test
description: URL: http://example.com
"""
        fixed = SkillLoader._fix_yaml_frontmatter(frontmatter)
        assert "description: \"URL: http://example.com\"" in fixed

    def test_fix_value_with_special_chars(self):
        """Test fixing values with special YAML characters."""
        frontmatter = """name: test
description: Array [1, 2, 3]
"""
        fixed = SkillLoader._fix_yaml_frontmatter(frontmatter)
        assert "description: \"Array [1, 2, 3]\"" in fixed

    def test_preserve_block_scalar_pipe(self):
        """Test that block scalar with pipe (|) is preserved."""
        frontmatter = """name: test
content: |
  Line 1
  Line 2
"""
        fixed = SkillLoader._fix_yaml_frontmatter(frontmatter)
        assert "content: |" in fixed

    def test_preserve_block_scalar_pipe_plus(self):
        """Test that block scalar with pipe-plus (|+) is preserved."""
        frontmatter = """name: test
content: |+
  Line 1
"""
        fixed = SkillLoader._fix_yaml_frontmatter(frontmatter)
        assert "content: |+" in fixed

    def test_preserve_block_scalar_pipe_minus(self):
        """Test that block scalar with pipe-minus (|-) is preserved."""
        frontmatter = """name: test
content: |-
  Line 1
"""
        fixed = SkillLoader._fix_yaml_frontmatter(frontmatter)
        assert "content: |-" in fixed

    def test_preserve_block_scalar_gt(self):
        """Test that block scalar with greater-than (>) is preserved."""
        frontmatter = """name: test
content: >
  Line 1
"""
        fixed = SkillLoader._fix_yaml_frontmatter(frontmatter)
        assert "content: >" in fixed

    def test_preserve_block_scalar_gt_plus(self):
        """Test that block scalar with greater-than-plus (>+ ) is preserved."""
        frontmatter = """name: test
content: >+
  Line 1
"""
        fixed = SkillLoader._fix_yaml_frontmatter(frontmatter)
        assert "content: >+" in fixed

    def test_preserve_block_scalar_gt_minus(self):
        """Test that block scalar with greater-than-minus (>- ) is preserved."""
        frontmatter = """name: test
content: >-
  Line 1
"""
        fixed = SkillLoader._fix_yaml_frontmatter(frontmatter)
        assert "content: >-" in fixed

    def test_preserve_quoted_values(self):
        """Test that already quoted values are preserved."""
        frontmatter = '''name: test
description: "Already quoted"
'''
        fixed = SkillLoader._fix_yaml_frontmatter(frontmatter)
        assert 'description: "Already quoted"' in fixed

    def test_skip_comment_lines(self):
        """Test that comment lines are preserved."""
        frontmatter = """# This is a comment
name: test
description: Test
"""
        fixed = SkillLoader._fix_yaml_frontmatter(frontmatter)
        assert "# This is a comment" in fixed

    def test_escape_value_with_quotes(self):
        """Test that double quotes in values are preserved (not escaped by _fix_yaml_frontmatter)."""
        frontmatter = """name: test
description: Say "hello" to YAML
"""
        fixed = SkillLoader._fix_yaml_frontmatter(frontmatter)
        assert 'description: Say "hello" to YAML' in fixed

    def test_fix_value_with_multiple_special_chars(self):
        """Test fixing values with multiple special characters."""
        frontmatter = """name: test
description: Test with {special} [chars] & more #tags
"""
        fixed = SkillLoader._fix_yaml_frontmatter(frontmatter)
        assert "description: \"Test with {special} [chars] & more #tags\"" in fixed


class TestSkillLoaderSplitFrontmatter:
    """Test SkillLoader._split_frontmatter method."""

    def test_split_valid_frontmatter(self):
        """Test splitting valid frontmatter."""
        content = """---
name: test
---
# Body
"""
        frontmatter, body = SkillLoader._split_frontmatter(content)
        assert frontmatter == "name: test"
        # Body includes trailing newline
        assert body.strip() == "# Body"

    def test_split_no_frontmatter(self):
        """Test splitting content without frontmatter."""
        content = "# Just body"
        frontmatter, body = SkillLoader._split_frontmatter(content)
        assert frontmatter is None
        assert body == "# Just body"

    def test_split_empty_frontmatter(self):
        """Test splitting with empty frontmatter returns None for frontmatter."""
        content = """---

# Body
"""
        frontmatter, body = SkillLoader._split_frontmatter(content)
        # Empty frontmatter returns None (because regex doesn't match empty content)
        assert frontmatter is None
        assert "# Body" in body


class TestSkillLoaderToSkillMd:
    """Test SkillLoader.to_skill_md method."""

    def test_to_skill_md_basic(self):
        """Test converting basic skill dict to SKILL.md."""
        skill_dict = {
            "name": "test-skill",
            "description": "A test skill",
            "content": "# Content"
        }
        result = SkillLoader.to_skill_md(skill_dict)
        assert "name: test-skill" in result
        assert "description: A test skill" in result
        assert "---\n" in result
        assert "# Content" in result

    def test_to_skill_md_with_allowed_tools(self):
        """Test converting skill dict with allowed-tools."""
        skill_dict = {
            "name": "tool-skill",
            "description": "A tool skill",
            "allowed-tools": ["tool1", "tool2"],
            "content": "# Body"
        }
        result = SkillLoader.to_skill_md(skill_dict)
        assert "allowed-tools:" in result
        assert "- tool1" in result
        assert "- tool2" in result

    def test_to_skill_md_with_tags(self):
        """Test converting skill dict with tags."""
        skill_dict = {
            "name": "tagged-skill",
            "description": "A tagged skill",
            "tags": ["python", "ml"],
            "content": "# Body"
        }
        result = SkillLoader.to_skill_md(skill_dict)
        assert "tags:" in result
        assert "- python" in result
        assert "- ml" in result


class TestSkillLoaderLoad:
    """Test SkillLoader.load method."""

    def test_load_file_not_found(self):
        """Test that loading non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            SkillLoader.load("/nonexistent/path/SKILL.md")

    def test_load_success(self, tmp_path):
        """Test successful loading of a skill file from disk."""
        skill_content = """---
name: loaded-skill
description: A skill loaded from file
allowed-tools:
  - tool1
tags:
  - test
---
# Loaded Content
This skill was loaded from a file.
"""
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(skill_content, encoding="utf-8")

        result = SkillLoader.load(str(skill_file))

        assert result["name"] == "loaded-skill"
        assert result["description"] == "A skill loaded from file"
        assert result["allowed_tools"] == ["tool1"]
        assert result["tags"] == ["test"]
        assert "Loaded Content" in result["content"]
        assert result["source_path"] == str(skill_file)


class TestSkillLoaderEdgeCases:
    """Test edge cases for SkillLoader."""

    def test_parse_with_invalid_yaml_falls_back_to_regex(self):
        """Test parsing with invalid YAML falls back to regex extraction."""
        content = """---
name: test
description: Test
    indented: value
---
# Body
"""
        # YAML parsing fails, but regex extraction succeeds since name/description are valid
        result = SkillLoader.parse(content)
        assert result["name"] == "test"
        assert result["description"] == "Test"

    def test_parse_empty_content(self):
        """Test parsing empty content."""
        with pytest.raises(ValueError):
            SkillLoader.parse("")

    def test_parse_multiline_description(self):
        """Test parsing with multiline description."""
        content = """---
name: test
description: >
  This is a
  multiline
  description
---
# Body
"""
        result = SkillLoader.parse(content)
        assert result["name"] == "test"
        assert "multiline" in result["description"]

    def test_parse_with_yaml_list_frontmatter_raises(self):
        """Test that YAML frontmatter which parses to a list raises ValueError."""
        content = """---
[item1, item2]
---
# Body
"""
        # Frontmatter is a YAML list (not a dict), so regex fallback extracts nothing
        # and raises because 'name' field is missing
        with pytest.raises(ValueError, match="'name' field"):
            SkillLoader.parse(content)

    def test_parse_with_block_sequence_frontmatter_raises(self):
        """Test that YAML frontmatter with block sequence raises ValueError."""
        content = """---
- item1
- item2
---
# Body
"""
        # Frontmatter is a YAML list (block sequence), so regex fallback extracts nothing
        # and raises because 'name' field is missing
        with pytest.raises(ValueError, match="'name' field"):
            SkillLoader.parse(content)

    def test_parse_with_inline_yaml_list(self):
        """Test parsing with inline YAML list at top level."""
        content = """---
!!seq [a, b, c]
---
# Body
"""
        with pytest.raises(Exception):
            SkillLoader.parse(content)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
