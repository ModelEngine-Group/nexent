"""
Unit tests for nexent.skills.skill_manager module.
"""
import io
import json
import os
import sys
import tempfile
import zipfile
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


class TempSkillDir:
    """Context manager for creating temporary skill directories."""

    def __init__(self):
        self.temp_dir = None
        self.skills_dir = None

    def __enter__(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_skills_")
        self.skills_dir = os.path.join(self.temp_dir, "skills")
        os.makedirs(self.skills_dir)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        import shutil

        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def create_skill(self, name: str, content: str, subdirs: Dict[str, Any] = None) -> None:
        """Create a skill with given name and content."""
        skill_dir = os.path.join(self.skills_dir, name)
        os.makedirs(skill_dir, exist_ok=True)

        skill_file = os.path.join(skill_dir, "SKILL.md")
        with open(skill_file, "w", encoding="utf-8") as f:
            f.write(content)

        if subdirs:
            for subdir, files in subdirs.items():
                subdir_path = os.path.join(skill_dir, subdir)
                os.makedirs(subdir_path, exist_ok=True)
                if isinstance(files, dict):
                    for filename, file_content in files.items():
                        file_path = os.path.join(subdir_path, filename)
                        os.makedirs(os.path.dirname(file_path), exist_ok=True)
                        with open(file_path, "w", encoding="utf-8") as f:
                            f.write(file_content if isinstance(file_content, str) else str(file_content))
                elif isinstance(files, list):
                    for file_info in files:
                        if isinstance(file_info, dict):
                            filename = file_info.get("name", "script.py")
                            file_content = file_info.get("content", "")
                            file_path = os.path.join(subdir_path, filename)
                            with open(file_path, "w", encoding="utf-8") as f:
                                f.write(file_content)


# Load skill_loader module directly without nexent package imports
import sys
import os
import importlib.util
from unittest.mock import MagicMock

# Mock the nexent.skills package before importing
mock_skills_module = MagicMock()
mock_skills_module.__path__ = [os.path.join(os.path.dirname(__file__), "../../../sdk/nexent/skills")]
sys.modules['nexent'] = MagicMock()
sys.modules['nexent.skills'] = mock_skills_module

# Load constants first
spec_const = importlib.util.spec_from_file_location(
    "nexent.skills.constants",
    os.path.join(os.path.dirname(__file__), "../../../sdk/nexent/skills/constants.py")
)
module_const = importlib.util.module_from_spec(spec_const)
spec_const.loader.exec_module(module_const)
sys.modules['nexent.skills.constants'] = module_const

# Load skill_loader module
spec_loader = importlib.util.spec_from_file_location(
    "nexent.skills.skill_loader",
    os.path.join(os.path.dirname(__file__), "../../../sdk/nexent/skills/skill_loader.py")
)
module_loader = importlib.util.module_from_spec(spec_loader)
spec_loader.loader.exec_module(module_loader)
sys.modules['nexent.skills.skill_loader'] = module_loader

# Load skill_manager module
spec_manager = importlib.util.spec_from_file_location(
    "nexent.skills.skill_manager",
    os.path.join(os.path.dirname(__file__), "../../../sdk/nexent/skills/skill_manager.py")
)
module_manager = importlib.util.module_from_spec(spec_manager)
spec_manager.loader.exec_module(module_manager)

SkillManager = module_manager.SkillManager
SkillNotFoundError = module_manager.SkillNotFoundError
SkillScriptNotFoundError = module_manager.SkillScriptNotFoundError
SkillLoader = module_loader.SkillLoader


class TestSkillManagerInit:
    """Test SkillManager initialization."""

    def test_init_with_all_params(self):
        """Test initialization with all parameters."""
        manager = SkillManager(
            local_skills_dir="/path/to/skills",
            agent_id=123,
            tenant_id="tenant-abc",
            version_no=1,
        )
        assert manager.local_skills_dir == "/path/to/skills"
        assert manager.agent_id == 123
        assert manager.tenant_id == "tenant-abc"
        assert manager.version_no == 1

    def test_init_with_defaults(self):
        """Test initialization with default values."""
        manager = SkillManager()
        assert manager.local_skills_dir is None
        assert manager.agent_id is None
        assert manager.tenant_id is None
        assert manager.version_no == 0


class TestSkillManagerListSkills:
    """Test SkillManager.list_skills method."""

    def test_list_skills_empty_dir(self):
        """Test listing skills from non-existent directory."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.list_skills()
            assert result == []

    def test_list_skills_with_valid_skills(self):
        """Test listing skills when directory contains valid skills."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "test-skill",
                """---
name: test-skill
description: A test skill
tags:
  - test
---
# Content
""",
            )

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.list_skills()

            assert len(result) == 1
            assert result[0]["name"] == "test-skill"
            assert result[0]["description"] == "A test skill"
            assert result[0]["tags"] == ["test"]

    def test_list_skills_ignores_non_directories(self):
        """Test that non-directory items are ignored."""
        with TempSkillDir() as temp:
            # Create a plain file (not a skill directory)
            plain_file = os.path.join(temp.skills_dir, "not_a_skill.txt")
            with open(plain_file, "w") as f:
                f.write("not a skill")

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.list_skills()
            assert result == []

    def test_list_skills_ignores_dirs_without_skill_file(self):
        """Test that directories without SKILL.md are ignored."""
        with TempSkillDir() as temp:
            # Create a directory without SKILL.md
            empty_dir = os.path.join(temp.skills_dir, "empty-skill")
            os.makedirs(empty_dir)

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.list_skills()
            assert result == []

    def test_list_skills_multiple_skills(self):
        """Test listing multiple skills."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "skill-one",
                """---
name: skill-one
description: First skill
---
# Content 1
""",
            )
            temp.create_skill(
                "skill-two",
                """---
name: skill-two
description: Second skill
---
# Content 2
""",
            )

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.list_skills()

            assert len(result) == 2
            names = {s["name"] for s in result}
            assert names == {"skill-one", "skill-two"}


class TestSkillManagerLoadSkill:
    """Test SkillManager.load_skill method."""

    def test_load_skill_success(self):
        """Test successful skill loading."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "my-skill",
                """---
name: my-skill
description: My skill description
allowed-tools:
  - tool1
tags:
  - python
---
# My Content
""",
            )

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.load_skill("my-skill")

            assert result is not None
            assert result["name"] == "my-skill"
            assert result["description"] == "My skill description"
            assert result["allowed_tools"] == ["tool1"]
            assert result["tags"] == ["python"]
            assert "My Content" in result["content"]

    def test_load_skill_not_found(self):
        """Test loading non-existent skill."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.load_skill("nonexistent")
            assert result is None

    def test_load_skill_no_local_dir(self):
        """Test loading skill when local_skills_dir is None."""
        manager = SkillManager(local_skills_dir=None)
        result = manager.load_skill("any-skill")
        assert result is None


class TestSkillManagerLoadSkillContent:
    """Test SkillManager.load_skill_content method."""

    def test_load_skill_content_success(self):
        """Test successful loading of skill content only."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "content-skill",
                """---
name: content-skill
description: Content test
---
# Actual Content
This is the body.
""",
            )

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.load_skill_content("content-skill")

            assert result is not None
            assert "Actual Content" in result
            assert "This is the body" in result

    def test_load_skill_content_not_found(self):
        """Test loading content of non-existent skill."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.load_skill_content("nonexistent")
            assert result is None


class TestSkillManagerSaveSkill:
    """Test SkillManager.save_skill method."""

    def test_save_skill_success(self):
        """Test successful skill saving."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)
            skill_data = {
                "name": "new-skill",
                "description": "A new skill",
                "content": "# New Skill Content",
            }

            result = manager.save_skill(skill_data)

            assert result is not None
            assert result["name"] == "new-skill"
            assert result["description"] == "A new skill"

            # Verify file was created
            skill_path = os.path.join(temp.skills_dir, "new-skill", "SKILL.md")
            assert os.path.exists(skill_path)

    def test_save_skill_without_name_raises(self):
        """Test that saving skill without name raises ValueError."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)
            skill_data = {
                "description": "No name skill",
                "content": "# Content",
            }

            with pytest.raises(ValueError, match="Skill name is required"):
                manager.save_skill(skill_data)

    def test_save_skill_overwrites_existing(self):
        """Test that saving existing skill overwrites it."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)

            # Save first version
            skill_data_v1 = {
                "name": "overwrite-skill",
                "description": "Version 1",
                "content": "# V1",
            }
            manager.save_skill(skill_data_v1)

            # Save second version
            skill_data_v2 = {
                "name": "overwrite-skill",
                "description": "Version 2",
                "content": "# V2",
            }
            result = manager.save_skill(skill_data_v2)

            assert result["description"] == "Version 2"

            # Verify only one skill file exists
            skill_dir = os.path.join(temp.skills_dir, "overwrite-skill")
            assert os.path.isdir(skill_dir)


class TestSkillManagerUploadSkillFromFile:
    """Test SkillManager.upload_skill_from_file method."""

    def test_upload_from_md_string(self):
        """Test uploading skill from MD string."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)
            md_content = """---
name: upload-md-skill
description: Uploaded from MD
---
# Uploaded Content
"""

            result = manager.upload_skill_from_file(md_content)

            assert result is not None
            assert result["name"] == "upload-md-skill"
            assert result["description"] == "Uploaded from MD"

    def test_upload_from_md_bytes(self):
        """Test uploading skill from MD bytes."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)
            md_content = b"""---
name: upload-bytes-skill
description: Uploaded from bytes
---
# Content
"""

            result = manager.upload_skill_from_file(md_content)

            assert result is not None
            assert result["name"] == "upload-bytes-skill"

    def test_upload_from_md_with_override_name(self):
        """Test uploading skill with name override."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)
            md_content = """---
name: original-name
description: Override test
---
# Content
"""

            result = manager.upload_skill_from_file(md_content, skill_name="override-name")

            assert result is not None
            assert result["name"] == "override-name"

    def test_upload_from_md_without_name_raises(self):
        """Test that MD without name and no override raises ValueError."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)
            md_content = """---
description: No name here
---
# Content
"""

            with pytest.raises(ValueError, match="Skill must have 'name' field"):
                manager.upload_skill_from_file(md_content)

    def test_upload_from_md_invalid_format_raises(self):
        """Test that invalid MD format raises ValueError."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)
            invalid_content = "Not valid frontmatter"

            with pytest.raises(ValueError, match="Invalid SKILL.md format"):
                manager.upload_skill_from_file(invalid_content)

    def test_upload_from_zip_bytes(self):
        """Test uploading skill from ZIP bytes."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)

            # Create ZIP in memory
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("my-zip-skill/SKILL.md", """---
name: my-zip-skill
description: From ZIP
---
# ZIP Content
""")
                zf.writestr("my-zip-skill/scripts/helper.py", "# Helper script\n")

            zip_bytes = zip_buffer.getvalue()
            result = manager.upload_skill_from_file(zip_bytes)

            assert result is not None
            assert result["name"] == "my-zip-skill"

            # Verify skill directory contents
            skill_dir = os.path.join(temp.skills_dir, "my-zip-skill")
            assert os.path.exists(os.path.join(skill_dir, "scripts", "helper.py"))

    def test_upload_from_zip_auto_detect(self):
        """Test that ZIP is auto-detected from magic bytes."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)

            # Create ZIP
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("auto-skill/SKILL.md", """---
name: auto-skill
description: Auto detected
---
# Content
""")

            zip_bytes = zip_buffer.getvalue()
            result = manager.upload_skill_from_file(zip_bytes)

            assert result is not None
            assert result["name"] == "auto-skill"

    def test_upload_from_zip_invalid_raises(self):
        """Test that invalid ZIP raises ValueError."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)
            # Create content that looks like ZIP (starts with PK) but is invalid
            invalid_zip = b"PK\x03\x04" + b"This is not a valid ZIP file content"

            with pytest.raises(ValueError, match="Invalid ZIP archive"):
                manager.upload_skill_from_file(invalid_zip)

    def test_upload_from_zip_without_skill_md_raises(self):
        """Test that ZIP without SKILL.md raises ValueError."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("no-skill/readme.txt", "Just a readme")

            zip_bytes = zip_buffer.getvalue()

            with pytest.raises(ValueError, match="SKILL.md not found"):
                manager.upload_skill_from_file(zip_bytes)

    def test_upload_from_zip_with_name_override(self):
        """Test uploading ZIP with skill name override."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("original-name/SKILL.md", """---
name: original-name
description: Override test
---
# Content
""")

            zip_bytes = zip_buffer.getvalue()
            result = manager.upload_skill_from_file(
                zip_bytes, skill_name="renamed-skill"
            )

            assert result is not None
            assert result["name"] == "renamed-skill"

    def test_upload_from_zip_bytesio(self):
        """Test uploading skill from BytesIO object."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("bytesio-skill/SKILL.md", """---
name: bytesio-skill
description: From BytesIO
---
# Content
""")

            # Seek to beginning before passing
            zip_buffer.seek(0)
            result = manager.upload_skill_from_file(zip_buffer)

            assert result is not None
            assert result["name"] == "bytesio-skill"


class TestSkillManagerUpdateSkillFromFile:
    """Test SkillManager.update_skill_from_file method."""

    def test_update_skill_md_success(self):
        """Test updating existing skill with MD."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)

            # Create initial skill
            temp.create_skill(
                "update-skill",
                """---
name: update-skill
description: Original
---
# Original Content
""",
            )

            # Update with new content
            new_content = """---
name: update-skill
description: Updated
---
# Updated Content
"""
            result = manager.update_skill_from_file(new_content, "update-skill")

            assert result is not None
            assert result["description"] == "Updated"

    def test_update_skill_not_found_raises(self):
        """Test updating non-existent skill raises ValueError."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)

            with pytest.raises(ValueError, match="Skill not found"):
                manager.update_skill_from_file(
                    b"""---
name: nonexistent
description: Test
---
# Content
""",
                    "nonexistent",
                )

    def test_update_skill_zip_success(self):
        """Test updating existing skill with ZIP."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)

            # Create initial skill
            temp.create_skill(
                "zip-update-skill",
                """---
name: zip-update-skill
description: Original
---
# Original Content
""",
            )

            # Update with ZIP
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("zip-update-skill/SKILL.md", """---
name: zip-update-skill
description: ZIP Updated
---
# ZIP Updated Content
""")
                zf.writestr("zip-update-skill/scripts/new_script.py", "# New script\n")

            zip_bytes = zip_buffer.getvalue()
            result = manager.update_skill_from_file(zip_bytes, "zip-update-skill")

            assert result is not None
            assert result["description"] == "ZIP Updated"


class TestSkillManagerDeleteSkill:
    """Test SkillManager.delete_skill method."""

    def test_delete_skill_success(self):
        """Test successful skill deletion."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "delete-me",
                """---
name: delete-me
description: To be deleted
---
# Content
""",
            )

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.delete_skill("delete-me")

            assert result is True

            # Verify directory is gone
            skill_dir = os.path.join(temp.skills_dir, "delete-me")
            assert not os.path.exists(skill_dir)

    def test_delete_skill_not_found_returns_true(self):
        """Test deleting non-existent skill returns True (idempotent)."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.delete_skill("nonexistent")
            assert result is True


class TestSkillManagerGetSkillFileTree:
    """Test SkillManager.get_skill_file_tree method."""

    def test_get_file_tree_success(self):
        """Test getting file tree for existing skill."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "tree-skill",
                """---
name: tree-skill
description: Tree test
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "analyze.py", "content": "# Script"}],
                    "assets": [{"name": "image.png", "content": "PNG_DATA"}],
                },
            )

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.get_skill_file_tree("tree-skill")

            assert result is not None
            assert result["name"] == "tree-skill"
            assert result["type"] == "directory"
            assert "children" in result

            # Check that SKILL.md is included
            child_names = [c["name"] for c in result["children"]]
            assert "SKILL.md" in child_names

    def test_get_file_tree_not_found(self):
        """Test getting file tree for non-existent skill."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.get_skill_file_tree("nonexistent")
            assert result is None

    def test_get_file_tree_nested_dirs(self):
        """Test getting file tree with nested directories."""
        with TempSkillDir() as temp:
            skill_dir = os.path.join(temp.skills_dir, "nested-skill")
            os.makedirs(skill_dir)

            # Create SKILL.md
            with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
                f.write("---\nname: nested-skill\ndescription: Nested\n---\n# Content\n")

            # Create nested structure
            nested_dir = os.path.join(skill_dir, "data", "configs")
            os.makedirs(nested_dir)
            with open(os.path.join(nested_dir, "config.json"), "w") as f:
                f.write('{"key": "value"}')

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.get_skill_file_tree("nested-skill")

            assert result is not None

            # Navigate to find nested config
            def find_child(node, name):
                for child in node.get("children", []):
                    if child["name"] == name:
                        return child
                return None

            data_node = find_child(result, "data")
            assert data_node is not None
            assert data_node["type"] == "directory"


class TestSkillManagerBuildSkillsSummary:
    """Test SkillManager.build_skills_summary method."""

    def test_build_summary_empty(self):
        """Test building summary with no skills."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.build_skills_summary()
            assert result == ""

    def test_build_summary_success(self):
        """Test building summary with skills."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "summary-skill",
                """---
name: summary-skill
description: For summary
---
# Content
""",
            )

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.build_skills_summary()

            assert "<skills>" in result
            assert "<name>summary-skill</name>" in result
            assert "<description>For summary</description>" in result
            assert "</skills>" in result

    def test_build_summary_with_whitelist(self):
        """Test building summary with available_skills whitelist."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "skill-one",
                """---
name: skill-one
description: First
---
# Content
""",
            )
            temp.create_skill(
                "skill-two",
                """---
name: skill-two
description: Second
---
# Content
""",
            )

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.build_skills_summary(available_skills=["skill-one"])

            assert "<name>skill-one</name>" in result
            assert "<name>skill-two</name>" not in result

    def test_build_summary_escapes_special_chars(self):
        """Test that special XML characters are escaped."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "escape-skill",
                """---
name: escape-skill
description: Test <tag> & "quotes"
---
# Content
""",
            )

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.build_skills_summary()

            assert "&lt;tag&gt;" in result
            assert "&amp;" in result


class TestSkillManagerLoadSkillDirectory:
    """Test SkillManager.load_skill_directory method."""

    def test_load_directory_success(self):
        """Test loading skill directory to temp location."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "dir-skill",
                """---
name: dir-skill
description: Directory test
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "run.py", "content": "# Script"}],
                },
            )

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.load_skill_directory("dir-skill")

            assert result is not None
            assert result["name"] == "dir-skill"
            assert "directory" in result
            assert os.path.exists(result["directory"])

            # Cleanup temp directory
            import shutil

            if os.path.exists(result["directory"]):
                shutil.rmtree(result["directory"])

    def test_load_directory_not_found(self):
        """Test loading non-existent skill directory."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.load_skill_directory("nonexistent")
            assert result is None


class TestSkillManagerGetSkillScripts:
    """Test SkillManager.get_skill_scripts method."""

    def test_get_scripts_success(self):
        """Test getting list of scripts in skill."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "script-skill",
                """---
name: script-skill
description: Scripts test
---
# Content
""",
                subdirs={
                    "scripts": [
                        {"name": "analyze.py", "content": "# Python script"},
                        {"name": "deploy.sh", "content": "# Shell script"},
                        {"name": "readme.txt", "content": "# Not a script"},
                    ],
                },
            )

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.get_skill_scripts("script-skill")

            assert len(result) == 2
            script_names = [os.path.basename(s) for s in result]
            assert "analyze.py" in script_names
            assert "deploy.sh" in script_names
            assert "readme.txt" not in script_names

    def test_get_scripts_no_scripts_dir(self):
        """Test getting scripts when no scripts directory exists."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "no-scripts",
                """---
name: no-scripts
description: No scripts
---
# Content
""",
            )

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.get_skill_scripts("no-scripts")
            assert result == []

    def test_get_scripts_not_found(self):
        """Test getting scripts for non-existent skill."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.get_skill_scripts("nonexistent")
            assert result == []


class TestSkillManagerCleanupSkillDirectory:
    """Test SkillManager.cleanup_skill_directory method."""

    def test_cleanup_removes_temp_dirs(self):
        """Test that cleanup removes temp directories."""
        import shutil

        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)

            # Create a fake temp directory matching pattern
            temp_base = tempfile.gettempdir()
            fake_temp = os.path.join(temp_base, f"skill_test-skill_{'fakeid'}")
            os.makedirs(fake_temp, exist_ok=True)
            with open(os.path.join(fake_temp, "test.txt"), "w") as f:
                f.write("temp content")

            manager.cleanup_skill_directory("test-skill")

            # Verify temp dir was removed
            assert not os.path.exists(fake_temp)


class TestSkillManagerRunSkillScript:
    """Test SkillManager.run_skill_script method."""

    def test_run_skill_script_not_found_raises(self):
        """Test running script in non-existent skill raises SkillNotFoundError."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)

            with pytest.raises(SkillNotFoundError, match="not found"):
                manager.run_skill_script("nonexistent", "scripts/test.py")

    def test_run_script_not_found_raises(self):
        """Test running non-existent script raises SkillScriptNotFoundError."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "run-skill",
                """---
name: run-skill
description: Run test
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "other.py", "content": "# Other"}],
                },
            )

            manager = SkillManager(local_skills_dir=temp.skills_dir)

            with pytest.raises(SkillScriptNotFoundError, match="not found"):
                manager.run_skill_script("run-skill", "scripts/missing.py")

    def test_run_python_script_success(self, mocker):
        """Test running Python script with mocked subprocess."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "py-script-skill",
                """---
name: py-script-skill
description: Python script
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "hello.py", "content": "print('Hello')"}],
                },
            )

            # Mock subprocess.run
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = '{"result": "success"}'
            mock_result.stderr = ""

            mocker.patch("subprocess.run", return_value=mock_result)

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.run_skill_script(
                "py-script-skill",
                "scripts/hello.py",
                params={"--name": "test"},
            )

            assert result == '{"result": "success"}'

    def test_run_python_script_error(self, mocker):
        """Test running Python script that returns error."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "error-script-skill",
                """---
name: error-script-skill
description: Error script
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "fail.py", "content": "raise Exception"}],
                },
            )

            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = ""
            mock_result.stderr = "Error occurred"

            mocker.patch("subprocess.run", return_value=mock_result)

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.run_skill_script("error-script-skill", "scripts/fail.py")

            # Should return JSON with error
            parsed = json.loads(result)
            assert "error" in parsed
            assert "Error occurred" in parsed["error"]

    def test_run_shell_script_success(self, mocker):
        """Test running shell script with mocked subprocess."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "sh-script-skill",
                """---
name: sh-script-skill
description: Shell script
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "deploy.sh", "content": "#!/bin/bash\necho done"}],
                },
            )

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "deployment complete"
            mock_result.stderr = ""

            mocker.patch("subprocess.run", return_value=mock_result)

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.run_skill_script("sh-script-skill", "scripts/deploy.sh")

            assert result == "deployment complete"

    def test_run_unsupported_script_type_raises(self):
        """Test running unsupported script type raises ValueError."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "unsupported-skill",
                """---
name: unsupported-skill
description: Unsupported
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "script.js", "content": "// JS"}],
                },
            )

            manager = SkillManager(local_skills_dir=temp.skills_dir)

            with pytest.raises(ValueError, match="Unsupported script type"):
                manager.run_skill_script("unsupported-skill", "scripts/script.js")


class TestSkillManagerBuildCommandArgs:
    """Test SkillManager._build_command_args method."""

    def test_build_command_string_param(self):
        """Test building command with string parameter."""
        manager = SkillManager()
        args = manager._build_command_args({"--name": "value"})

        assert "--name" in args
        assert "value" in args

    def test_build_command_boolean_true(self):
        """Test building command with boolean True parameter."""
        manager = SkillManager()
        args = manager._build_command_args({"--verbose": True})

        assert "--verbose" in args
        assert len(args) == 1

    def test_build_command_boolean_false(self):
        """Test building command with boolean False parameter (excluded)."""
        manager = SkillManager()
        args = manager._build_command_args({"--quiet": False})

        assert "--quiet" not in args
        assert len(args) == 0

    def test_build_command_list_param(self):
        """Test building command with list parameter."""
        manager = SkillManager()
        args = manager._build_command_args({"-i": ["a", "b", "c"]})

        assert args == ["-i", "a", "-i", "b", "-i", "c"]

    def test_build_command_none_value(self):
        """Test that None values are excluded."""
        manager = SkillManager()
        args = manager._build_command_args({"--opt": None})

        assert len(args) == 0


class TestSkillManagerEdgeCases:
    """Test edge cases for SkillManager."""

    def test_load_skill_from_corrupted_file(self):
        """Test loading skill with corrupted content."""
        with TempSkillDir() as temp:
            skill_dir = os.path.join(temp.skills_dir, "corrupted")
            os.makedirs(skill_dir)
            skill_file = os.path.join(skill_dir, "SKILL.md")
            with open(skill_file, "w", encoding="utf-8") as f:
                f.write("not valid yaml frontmatter at all")

            manager = SkillManager(local_skills_dir=temp.skills_dir)

            # Should not raise, just skip the skill
            skills = manager.list_skills()
            assert len(skills) == 0

    def test_delete_skill_with_nested_content(self):
        """Test deleting skill with nested directory structure."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "nested-delete",
                """---
name: nested-delete
description: Nested delete test
---
# Content
""",
                subdirs={
                    "data": {
                        "configs": {"app.json": '{"key": "value"}'},
                    },
                },
            )

            manager = SkillManager(local_skills_dir=temp.skills_dir)
            result = manager.delete_skill("nested-delete")

            assert result is True
            skill_dir = os.path.join(temp.skills_dir, "nested-delete")
            assert not os.path.exists(skill_dir)

    def test_upload_md_with_explicit_file_type(self):
        """Test uploading MD with explicit file_type parameter."""
        with TempSkillDir() as temp:
            manager = SkillManager(local_skills_dir=temp.skills_dir)
            md_content = """---
name: explicit-type
description: Explicit type test
---
# Content
"""

            result = manager.upload_skill_from_file(
                md_content, file_type="md"
            )

            assert result is not None
            assert result["name"] == "explicit-type"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
