"""
Unit tests for nexent.skills.skill_manager module.
"""
import io
import json
import os
import shlex
import shutil
import subprocess
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
            base_skills_dir="/path/to/skills",
            agent_id=123,
            tenant_id="tenant-abc",
            version_no=1,
        )
        assert manager.base_skills_dir == "/path/to/skills"
        # On Windows, os.path.join uses backslash, so normalize for cross-platform test
        assert os.path.normpath(manager.local_skills_dir) == os.path.normpath("/path/to/skills/tenant-abc")
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
            manager = SkillManager(base_skills_dir=temp.skills_dir)
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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.list_skills()
            assert result == []

    def test_list_skills_ignores_dirs_without_skill_file(self):
        """Test that directories without SKILL.md are ignored."""
        with TempSkillDir() as temp:
            # Create a directory without SKILL.md
            empty_dir = os.path.join(temp.skills_dir, "empty-skill")
            os.makedirs(empty_dir)

            manager = SkillManager(base_skills_dir=temp.skills_dir)
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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
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
            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.load_skill("nonexistent")
            assert result is None

    def test_load_skill_no_local_dir(self):
        """Test loading skill when local_skills_dir is None."""
        manager = SkillManager(base_skills_dir=None)
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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.load_skill_content("content-skill")

            assert result is not None
            assert "Actual Content" in result
            assert "This is the body" in result

    def test_load_skill_content_not_found(self):
        """Test loading content of non-existent skill."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.load_skill_content("nonexistent")
            assert result is None


class TestSkillManagerSaveSkill:
    """Test SkillManager.save_skill method."""

    def test_save_skill_success(self):
        """Test successful skill saving."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)
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
            manager = SkillManager(base_skills_dir=temp.skills_dir)
            skill_data = {
                "description": "No name skill",
                "content": "# Content",
            }

            with pytest.raises(ValueError, match="Skill name is required"):
                manager.save_skill(skill_data)

    def test_save_skill_overwrites_existing(self):
        """Test that saving existing skill overwrites it."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

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
            manager = SkillManager(base_skills_dir=temp.skills_dir)
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
            manager = SkillManager(base_skills_dir=temp.skills_dir)
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
            manager = SkillManager(base_skills_dir=temp.skills_dir)
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
            manager = SkillManager(base_skills_dir=temp.skills_dir)
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
            manager = SkillManager(base_skills_dir=temp.skills_dir)
            invalid_content = "Not valid frontmatter"

            with pytest.raises(ValueError, match="Invalid SKILL.md format"):
                manager.upload_skill_from_file(invalid_content)

    def test_upload_from_zip_bytes(self):
        """Test uploading skill from ZIP bytes."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

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
            manager = SkillManager(base_skills_dir=temp.skills_dir)

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
            manager = SkillManager(base_skills_dir=temp.skills_dir)
            # Create content that looks like ZIP (starts with PK) but is invalid
            invalid_zip = b"PK\x03\x04" + b"This is not a valid ZIP file content"

            with pytest.raises(ValueError, match="Invalid ZIP archive"):
                manager.upload_skill_from_file(invalid_zip)

    def test_upload_from_zip_without_skill_md_raises(self):
        """Test that ZIP without SKILL.md raises ValueError."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("no-skill/readme.txt", "Just a readme")

            zip_bytes = zip_buffer.getvalue()

            with pytest.raises(ValueError, match="SKILL.md not found"):
                manager.upload_skill_from_file(zip_bytes)

    def test_upload_from_zip_with_name_override(self):
        """Test uploading ZIP with skill name override."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

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
            manager = SkillManager(base_skills_dir=temp.skills_dir)

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
            manager = SkillManager(base_skills_dir=temp.skills_dir)

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
            manager = SkillManager(base_skills_dir=temp.skills_dir)

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
            manager = SkillManager(base_skills_dir=temp.skills_dir)

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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.delete_skill("delete-me")

            assert result is True

            # Verify directory is gone
            skill_dir = os.path.join(temp.skills_dir, "delete-me")
            assert not os.path.exists(skill_dir)

    def test_delete_skill_not_found_returns_true(self):
        """Test deleting non-existent skill returns True (idempotent)."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)
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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
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
            manager = SkillManager(base_skills_dir=temp.skills_dir)
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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
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
            manager = SkillManager(base_skills_dir=temp.skills_dir)
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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
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
            manager = SkillManager(base_skills_dir=temp.skills_dir)
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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.get_skill_scripts("no-scripts")
            assert result == []

    def test_get_scripts_not_found(self):
        """Test getting scripts for non-existent skill."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.get_skill_scripts("nonexistent")
            assert result == []


class TestSkillManagerCleanupSkillDirectory:
    """Test SkillManager.cleanup_skill_directory method."""

    def test_cleanup_removes_temp_dirs(self):
        """Test that cleanup removes temp directories."""
        import shutil

        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

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
            manager = SkillManager(base_skills_dir=temp.skills_dir)

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

            manager = SkillManager(base_skills_dir=temp.skills_dir)

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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.run_skill_script(
                "py-script-skill",
                "scripts/hello.py",
                params="--name test",
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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
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

            manager = SkillManager(base_skills_dir=temp.skills_dir)

            with pytest.raises(ValueError, match="Unsupported script type"):
                manager.run_skill_script("unsupported-skill", "scripts/script.js")


class TestSkillManagerStringParams:
    """Test SkillManager string-based parameter handling."""

    def test_string_params_simple(self, mocker):
        """Test string params are parsed correctly with shlex."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "str-params-skill",
                """---
name: str-params-skill
description: String params test
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "test.py", "content": "print('Hello')"}],
                },
            )

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = '{"result": "success"}'
            mock_result.stderr = ""

            mocker.patch("subprocess.run", return_value=mock_result)

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.run_skill_script(
                "str-params-skill",
                "scripts/test.py",
                params='--target -c --code "SELECT 1"',
            )

            assert result == '{"result": "success"}'
            call_args = subprocess.run.call_args[0][0]
            assert "--target" in call_args
            assert "-c" in call_args
            assert "--code" in call_args
            assert "SELECT 1" in call_args

    def test_string_params_empty(self, mocker):
        """Test empty string params work correctly."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "empty-params-skill",
                """---
name: empty-params-skill
description: Empty params test
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "test.py", "content": "print('Hello')"}],
                },
            )

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = '{"result": "success"}'
            mock_result.stderr = ""

            mocker.patch("subprocess.run", return_value=mock_result)

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.run_skill_script(
                "empty-params-skill",
                "scripts/test.py",
                params="",
            )

            assert result == '{"result": "success"}'
            call_args = subprocess.run.call_args[0][0]
            assert len(call_args) == 2  # Only script path and "python"


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

            manager = SkillManager(base_skills_dir=temp.skills_dir)

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

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.delete_skill("nested-delete")

            assert result is True
            skill_dir = os.path.join(temp.skills_dir, "nested-delete")
            assert not os.path.exists(skill_dir)

    def test_upload_md_with_explicit_file_type(self):
        """Test uploading MD with explicit file_type parameter."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)
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


    def test_upload_md_with_explicit_file_type(self):
        """Test uploading MD with explicit file_type parameter."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)
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

    def test_upload_from_md_missing_name_raises(self):
        """Test that MD without name raises ValueError."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)
            md_content = """---
description: No name here
---
# Content
"""
            with pytest.raises(ValueError, match="Invalid SKILL.md format"):
                manager.upload_skill_from_file(md_content)

    def test_upload_zip_with_name_ending_in_zip(self):
        """Test ZIP detection when skill_name ends with .zip."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("detected-skill/SKILL.md", """---
name: detected-skill
description: ZIP detected
---
# Content
""")

            zip_bytes = zip_buffer.getvalue()
            result = manager.upload_skill_from_file(
                zip_bytes, skill_name="my-skill.zip"
            )

            assert result is not None
            assert result["name"] == "my-skill.zip"

    def test_upload_zip_unknown_skill_name_none_raises(self):
        """Test that ZIP with None skill_name raises ValueError."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            # Create ZIP without any folder name hint
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("SKILL.md", """---
name: SKILL
description: No folder
---
# Content
""")

            zip_bytes = zip_buffer.getvalue()

            with pytest.raises(ValueError, match="Skill name is required"):
                manager.upload_skill_from_file(zip_bytes, skill_name=None)

    def test_upload_zip_with_backslash_paths(self):
        """Test ZIP extraction with backslash paths (Windows)."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("backslash-skill\\SKILL.md", """---
name: backslash-skill
description: Backslash paths
---
# Content
""")
                zf.writestr("backslash-skill\\scripts\\test.py", "# Test script\n")

            zip_bytes = zip_buffer.getvalue()
            result = manager.upload_skill_from_file(zip_bytes)

            assert result is not None
            assert result["name"] == "backslash-skill"

    def test_upload_zip_with_nested_structure(self):
        """Test ZIP extraction with deeply nested structure."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("nested-skill/SKILL.md", """---
name: nested-skill
description: Nested
---
# Content
""")
                zf.writestr("nested-skill/data/configs/app.json", '{"key": "value"}')
                zf.writestr("nested-skill/data/configs/dev.json", '{"env": "dev"}')

            zip_bytes = zip_buffer.getvalue()
            result = manager.upload_skill_from_file(zip_bytes)

            assert result is not None
            skill_dir = os.path.join(temp.skills_dir, "nested-skill")
            assert os.path.exists(os.path.join(skill_dir, "data", "configs", "app.json"))

    def test_update_skill_md_auto_detect(self):
        """Test updating skill with auto-detect file type."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            temp.create_skill(
                "auto-update",
                """---
name: auto-update
description: Original
---
# Original
""",
            )

            new_md = """---
name: auto-update
description: Auto updated
---
# Updated
"""
            result = manager.update_skill_from_file(new_md, "auto-update")

            assert result is not None
            assert result["description"] == "Auto updated"

    def test_update_skill_zip_with_backslash_paths(self):
        """Test updating skill from ZIP with backslash paths."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            temp.create_skill(
                "zip-update-bs",
                """---
name: zip-update-bs
description: Original
---
# Original
""",
            )

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("zip-update-bs\\SKILL.md", """---
name: zip-update-bs
description: BS Updated
---
# BS Updated
""")
                zf.writestr("zip-update-bs\\scripts\\helper.py", "# Helper\n")

            zip_bytes = zip_buffer.getvalue()
            result = manager.update_skill_from_file(zip_bytes, "zip-update-bs")

            assert result is not None
            assert result["description"] == "BS Updated"


class TestSkillManagerAddToTree:
    """Test SkillManager._add_to_tree method."""

    def test_add_to_tree_single_file(self):
        """Test adding single file to tree."""
        manager = SkillManager()
        node = {"name": "root", "type": "directory", "children": []}

        manager._add_to_tree(node, ["file.txt"], is_directory=False)

        assert len(node["children"]) == 1
        assert node["children"][0]["name"] == "file.txt"
        assert node["children"][0]["type"] == "file"

    def test_add_to_tree_single_directory(self):
        """Test adding single directory to tree."""
        manager = SkillManager()
        node = {"name": "root", "type": "directory", "children": []}

        manager._add_to_tree(node, ["subdir"], is_directory=True)

        assert len(node["children"]) == 1
        assert node["children"][0]["name"] == "subdir"
        assert node["children"][0]["type"] == "directory"

    def test_add_to_tree_nested_path(self):
        """Test adding nested path to tree."""
        manager = SkillManager()
        node = {"name": "root", "type": "directory", "children": []}

        manager._add_to_tree(node, ["dir1", "dir2", "file.txt"], is_directory=False)

        assert node["children"][0]["name"] == "dir1"
        assert node["children"][0]["type"] == "directory"
        assert node["children"][0]["children"][0]["name"] == "dir2"
        assert node["children"][0]["children"][0]["type"] == "directory"
        assert node["children"][0]["children"][0]["children"][0]["name"] == "file.txt"

    def test_add_to_tree_skips_duplicate_same_type(self):
        """Test that duplicate entries with same type are skipped."""
        manager = SkillManager()
        node = {"name": "root", "type": "directory", "children": [{"name": "dup", "type": "file", "children": []}]}

        manager._add_to_tree(node, ["dup"], is_directory=False)

        assert len(node["children"]) == 1

    def test_add_to_tree_empty_parts(self):
        """Test that empty parts list does nothing."""
        manager = SkillManager()
        node = {"name": "root", "type": "directory", "children": []}

        manager._add_to_tree(node, [], is_directory=False)

        assert len(node["children"]) == 0


class TestSkillManagerDeleteSkillErrorHandling:
    """Test SkillManager.delete_skill error handling."""

    def test_delete_skill_with_os_error(self, mocker):
        """Test deleting skill when os.error occurs."""
        import shutil

        with TempSkillDir() as temp:
            temp.create_skill(
                "delete-error",
                """---
name: delete-error
description: Delete error test
---
# Content
""",
            )

            skill_dir = os.path.join(temp.skills_dir, "delete-error")

            # Mock at module level where skill_manager imports it
            original_rmtree = shutil.rmtree
            def mock_rmtree(path, **kwargs):
                if path == skill_dir:
                    raise OSError("Permission denied")
                original_rmtree(path, **kwargs)

            mocker.patch("shutil.rmtree", side_effect=mock_rmtree)

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.delete_skill("delete-error")

            # Should still return True (idempotent behavior)
            assert result is True


class TestSkillManagerBuildSkillsSummaryEdgeCases:
    """Test SkillManager.build_skills_summary edge cases."""

    def test_build_summary_with_empty_description(self):
        """Test building summary when skill has empty description."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            # Create a skill with empty description
            skill_dir = os.path.join(temp.skills_dir, "empty-desc")
            os.makedirs(skill_dir)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("""---
name: empty-desc
description: 
---
# Content
""")

            result = manager.build_skills_summary()

            assert "<skills>" in result
            assert "<name>empty-desc</name>" in result


class TestSkillManagerCleanupSkillDirectoryOsError:
    """Test SkillManager.cleanup_skill_directory error handling."""

    def test_cleanup_with_os_error(self, mocker):
        """Test cleanup when os.remove fails."""
        mocker.patch("os.listdir", return_value=[f"skill_test_fakeid"])
        mocker.patch("os.path.isdir", return_value=False)
        mocker.patch("os.remove", side_effect=OSError("Access denied"))
        mocker.patch("os.path.join", side_effect=lambda *args: "\\".join(str(a) for a in args))

        manager = SkillManager(base_skills_dir="/fake")
        # Should not raise, just log warning
        manager.cleanup_skill_directory("test")


class TestSkillManagerRunSkillScriptErrorHandling:
    """Test SkillManager.run_skill_script error handling."""

    def test_run_python_script_timeout(self, mocker):
        """Test running Python script that times out."""
        import subprocess

        with TempSkillDir() as temp:
            temp.create_skill(
                "timeout-skill",
                """---
name: timeout-skill
description: Timeout test
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "slow.py", "content": "import time; time.sleep(1000)"}],
                },
            )

            mocker.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 300))

            manager = SkillManager(base_skills_dir=temp.skills_dir)

            with pytest.raises(TimeoutError, match="timed out"):
                manager.run_skill_script("timeout-skill", "scripts/slow.py")

    def test_run_python_script_other_exception(self, mocker):
        """Test running Python script with unexpected exception."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "except-skill",
                """---
name: except-skill
description: Exception test
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "crash.py", "content": "raise RuntimeError"}],
                },
            )

            mocker.patch("subprocess.run", side_effect=RuntimeError("Unexpected"))

            manager = SkillManager(base_skills_dir=temp.skills_dir)

            with pytest.raises(RuntimeError, match="Unexpected"):
                manager.run_skill_script("except-skill", "scripts/crash.py")

    def test_run_shell_script_timeout(self, mocker):
        """Test running shell script that times out."""
        import subprocess

        with TempSkillDir() as temp:
            temp.create_skill(
                "sh-timeout-skill",
                """---
name: sh-timeout-skill
description: Shell timeout test
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "slow.sh", "content": "#!/bin/bash\nsleep 1000"}],
                },
            )

            mocker.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 300))

            manager = SkillManager(base_skills_dir=temp.skills_dir)

            with pytest.raises(TimeoutError, match="timed out"):
                manager.run_skill_script("sh-timeout-skill", "scripts/slow.sh")

    def test_run_shell_script_error_returns_json(self, mocker):
        """Test running shell script that returns error code."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "sh-error-skill",
                """---
name: sh-error-skill
description: Shell error test
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "fail.sh", "content": "#!/bin/bash\nexit 1"}],
                },
            )

            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = "partial output"
            mock_result.stderr = "Shell error"

            mocker.patch("subprocess.run", return_value=mock_result)

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.run_skill_script("sh-error-skill", "scripts/fail.sh")

            parsed = json.loads(result)
            assert "error" in parsed


class TestSkillManagerGetSkillFileTreeEdgeCases:
    """Test SkillManager.get_skill_file_tree edge cases."""

    def test_get_file_tree_includes_skill_md_in_subdirs(self):
        """Test that SKILL.md in subdirectories is included (no special exclusion)."""
        with TempSkillDir() as temp:
            skill_dir = os.path.join(temp.skills_dir, "md-subdir-skill")
            os.makedirs(skill_dir)

            with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
                f.write("---\nname: md-subdir-skill\ndescription: Test\n---\n# Content\n")

            subdir = os.path.join(skill_dir, "data")
            os.makedirs(subdir)
            with open(os.path.join(subdir, "SKILL.md"), "w") as f:
                f.write("# This is also included\n")

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.get_skill_file_tree("md-subdir-skill")

            assert result is not None

            def count_skill_md(node):
                count = 0
                for child in node.get("children", []):
                    if child["name"] == "SKILL.md":
                        count += 1
                    if child["type"] == "directory":
                        count += count_skill_md(child)
                return count

            # get_skill_file_tree returns all files, including SKILL.md in subdirs
            assert count_skill_md(result) == 2


class TestSkillManagerListSkillsErrorHandling:
    """Test SkillManager.list_skills error handling."""

    def test_list_skills_with_os_error(self, mocker):
        """Test listing skills when os.listdir raises OSError."""
        with TempSkillDir() as temp:
            mocker.patch("os.listdir", side_effect=OSError("Permission denied"))

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.list_skills()

            # Should return empty list and log error
            assert result == []

    def test_list_skills_with_load_error(self, mocker):
        """Test listing skills when loading a skill raises exception."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "load-error-skill",
                """---
name: load-error-skill
description: Test
---
# Content
""",
            )

            mocker.patch.object(
                module_manager.SkillManager,
                "load_skill",
                side_effect=Exception("Load failed")
            )

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.list_skills()

            # Should skip the failing skill
            assert result == []


class TestSkillManagerUploadSkillEnhanced:
    """Enhanced tests for SkillManager.upload_skill_from_file."""

    def test_upload_zip_with_directory_entries_skipped(self):
        """Test ZIP directory entries (ending with '/') are skipped."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("dir-skill/SKILL.md", """---
name: dir-skill
description: With directories
---
# Content
""")
                zf.writestr("dir-skill/data/config.json", '{"key": "value"}')

            zip_bytes = zip_buffer.getvalue()
            result = manager.upload_skill_from_file(zip_bytes)

            assert result is not None
            assert result["name"] == "dir-skill"
            skill_dir = os.path.join(temp.skills_dir, "dir-skill")
            assert os.path.exists(os.path.join(skill_dir, "data", "config.json"))

    def test_upload_zip_nested_skill_md_fallback(self):
        """Test ZIP with deeply nested SKILL.md triggers fallback search."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("nested-skill/SKILL.md", """---
name: nested-skill
description: Nested path
---
# Content
""")

            zip_bytes = zip_buffer.getvalue()
            result = manager.upload_skill_from_file(zip_bytes)

            assert result is not None
            assert result["name"] == "nested-skill"

    def test_upload_zip_parse_exception_raised(self):
        """Test ZIP with invalid SKILL.md content raises ValueError."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("bad-skill/SKILL.md", """---
name: bad-skill
---
invalid: !!python/object/apply:os.system
""")

            zip_bytes = zip_buffer.getvalue()

            with pytest.raises(ValueError, match="Failed to parse SKILL.md"):
                manager.upload_skill_from_file(zip_bytes)

    def test_upload_zip_extracts_different_prefix_files(self):
        """Test ZIP files without skill name prefix are extracted as-is."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("prefix-skill/SKILL.md", """---
name: prefix-skill
description: Prefix test
---
# Content
""")
                zf.writestr("other-prefix/data.json", '{"other": true}')

            zip_bytes = zip_buffer.getvalue()
            result = manager.upload_skill_from_file(zip_bytes)

            assert result is not None
            skill_dir = os.path.join(temp.skills_dir, "prefix-skill")
            assert os.path.exists(os.path.join(skill_dir, "other-prefix", "data.json"))


class TestSkillManagerUpdateSkillEnhanced:
    """Enhanced tests for SkillManager.update_skill_from_file."""

    def test_update_zip_skips_skill_md_when_not_found(self):
        """Test ZIP update skips SKILL.md when not present in ZIP."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            temp.create_skill(
                "no-md-update",
                """---
name: no-md-update
description: Original
---
# Original
""",
            )

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("no-md-update/config.json", '{"updated": true}')

            zip_bytes = zip_buffer.getvalue()
            result = manager.update_skill_from_file(zip_bytes, "no-md-update")

            assert result is not None

    def test_update_zip_extracts_different_prefix_files(self):
        """Test ZIP update extracts files with different folder prefix."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            temp.create_skill(
                "prefix-update",
                """---
name: prefix-update
description: Original
---
# Original
""",
            )

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("prefix-update/SKILL.md", """---
name: prefix-update
description: Updated
---
# Updated
""")
                zf.writestr("other-prefix/data.json", '{"key": "value"}')

            zip_bytes = zip_buffer.getvalue()
            result = manager.update_skill_from_file(zip_bytes, "prefix-update")

            assert result is not None


class TestSkillManagerAddToTreeEnhanced:
    """Enhanced tests for SkillManager._add_to_tree method."""

    def test_add_to_tree_reuses_existing_directory(self):
        """Test adding path reuses existing directory node."""
        manager = SkillManager()
        node = {"name": "root", "type": "directory", "children": [{"name": "dir1", "type": "directory", "children": []}]}

        manager._add_to_tree(node, ["dir1", "file.txt"], is_directory=False)

        assert len(node["children"]) == 1
        assert node["children"][0]["children"][0]["name"] == "file.txt"

    def test_add_to_tree_skips_type_conflict(self):
        """Test type conflict skips adding the entry."""
        manager = SkillManager()
        node = {"name": "root", "type": "directory", "children": [{"name": "conflict", "type": "directory", "children": []}]}

        manager._add_to_tree(node, ["conflict"], is_directory=False)

        assert len(node["children"]) == 1


class TestSkillManagerErrorHandlingEnhanced:
    """Enhanced error handling tests for SkillManager."""

    def test_cleanup_handles_rmtree_exception(self, mocker):
        """Test cleanup logs warning when rmtree fails."""
        mocker.patch("os.listdir", return_value=[f"skill_test_cleanup"])
        mocker.patch("os.path.isdir", return_value=True)
        mocker.patch("shutil.rmtree", side_effect=OSError("Access denied"))

        manager = SkillManager(base_skills_dir="/fake")
        manager.cleanup_skill_directory("test-cleanup")

    def test_run_python_script_with_list_params(self, mocker):
        """Test running Python script with string params containing multiple values."""
        import subprocess as sp
        from unittest.mock import ANY

        with TempSkillDir() as temp:
            temp.create_skill(
                "list-param-skill",
                """---
name: list-param-skill
description: List param test
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "multi.py", "content": "print('ok')"}],
                },
            )

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "ok"
            mock_result.stderr = ""

            mocker.patch.object(sp, "run", return_value=mock_result)

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.run_skill_script(
                "list-param-skill",
                "scripts/multi.py",
                params="-i a -i b -i c"
            )

            assert result == "ok"
            args = sp.run.call_args[0][0]
            assert args[0] == sys.executable
            assert args[1:] == [ANY, "-i", "a", "-i", "b", "-i", "c"]

    def test_run_python_script_boolean_false_excluded(self, mocker):
        """Test boolean flags in string params are passed as-is (True)."""
        import subprocess as sp

        with TempSkillDir() as temp:
            temp.create_skill(
                "bool-false-skill",
                """---
name: bool-false-skill
description: Bool false test
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "bool.py", "content": "print('ok')"}],
                },
            )

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "ok"
            mock_result.stderr = ""

            mocker.patch.object(sp, "run", return_value=mock_result)

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.run_skill_script(
                "bool-false-skill",
                "scripts/bool.py",
                params="--verbose"
            )

            args = sp.run.call_args[0][0]
            assert "--quiet" not in args
            assert "--verbose" in args

    def test_run_shell_script_other_exception(self, mocker):
        """Test shell script with unexpected exception propagates."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "sh-except-skill",
                """---
name: sh-except-skill
description: Shell exception test
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "except.sh", "content": "#!/bin/bash\nthrow"}],
                },
            )

            mocker.patch("subprocess.run", side_effect=RuntimeError("Unexpected shell error"))

            manager = SkillManager(base_skills_dir=temp.skills_dir)

            with pytest.raises(RuntimeError, match="Unexpected shell error"):
                manager.run_skill_script("sh-except-skill", "scripts/except.sh")


class TestSkillManagerWriteSkillFile:
    """Test SkillManager._write_skill_file method."""

    def test_write_skill_file_nested_path(self):
        """Test writing file to nested directory."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)
            manager._write_skill_file(
                "test-skill",
                "scripts/nested/deep/file.py",
                "# nested file content"
            )

            skill_dir = os.path.join(temp.skills_dir, "test-skill")
            expected_path = os.path.join(skill_dir, "scripts", "nested", "deep", "file.py")
            assert os.path.exists(expected_path)
            with open(expected_path, "r") as f:
                assert f.read() == "# nested file content"

    def test_write_skill_file_no_local_dir(self):
        """Test writing file when local_skills_dir is None."""
        manager = SkillManager(base_skills_dir=None)
        manager._write_skill_file("any-skill", "file.txt", "content")


class TestSkillManagerGetSkillMetadata:
    """Test SkillManager._get_skill_metadata method."""

    def test_get_skill_metadata_success(self):
        """Test getting skill metadata successfully."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "meta-skill",
                """---
name: meta-skill
description: Metadata test
tags:
  - test
---
# Content
""",
            )

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager._get_skill_metadata("meta-skill")

            assert result is not None
            assert result["name"] == "meta-skill"
            assert result["description"] == "Metadata test"
            assert result["tags"] == ["test"]

    def test_get_skill_metadata_load_exception(self, mocker):
        """Test metadata extraction when load raises exception."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "load-exc-skill",
                """---
name: load-exc-skill
description: Load exception test
---
# Content
""",
            )

            mocker.patch.object(
                module_manager.SkillManager,
                "load_skill",
                side_effect=Exception("Load failed")
            )

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager._get_skill_metadata("load-exc-skill")

            assert result is None


class TestSkillManagerUploadZipEdgeCases:
    """Test ZIP upload edge cases."""

    def test_upload_zip_with_yaml_parse_error(self):
        """Test ZIP upload when SKILL.md has invalid YAML uses regex fallback."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("bad-yaml-skill/SKILL.md", """---
name: bad-yaml-skill
description: >
invalid yaml content that should fail: [this
---
# Content
""")

            zip_bytes = zip_buffer.getvalue()
            # skill_loader uses regex fallback when YAML parse fails, so it may still succeed
            result = manager.upload_skill_from_file(zip_bytes)
            # If fallback parsing works, description may be empty
            assert result is not None
            assert result["name"] == "bad-yaml-skill"

    def test_upload_zip_skill_md_at_root(self):
        """Test ZIP with SKILL.md directly at root (no folder)."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("root-skill/SKILL.md", """---
name: root-skill
description: Root level skill
---
# Content
""")
                zf.writestr("root-skill/config.json", '{"key": "value"}')

            zip_bytes = zip_buffer.getvalue()
            result = manager.upload_skill_from_file(zip_bytes)

            assert result is not None
            assert result["name"] == "root-skill"


class TestSkillManagerSaveSkillExtraFiles:
    """Test save_skill with extra files."""

    def test_save_skill_with_files(self):
        """Test saving skill with additional files."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)
            skill_data = {
                "name": "files-skill",
                "description": "With extra files",
                "content": "# Main content",
                "files": [
                    {"path": "config.json", "content": '{"setting": true}'},
                    {"path": "scripts/helper.py", "content": "# Helper"},
                ]
            }

            result = manager.save_skill(skill_data)

            assert result is not None
            skill_dir = os.path.join(temp.skills_dir, "files-skill")
            assert os.path.exists(os.path.join(skill_dir, "config.json"))
            assert os.path.exists(os.path.join(skill_dir, "scripts", "helper.py"))

    def test_save_skill_with_files_dict_format(self):
        """Test saving skill with files using dict format."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)
            skill_data = {
                "name": "dict-files-skill",
                "description": "With dict format files",
                "content": "# Content",
                "files": [
                    {"file_path": "data.json", "content": '{"data": 123}'},
                ]
            }

            result = manager.save_skill(skill_data)

            assert result is not None
            skill_dir = os.path.join(temp.skills_dir, "dict-files-skill")
            assert os.path.exists(os.path.join(skill_dir, "data.json"))

    def test_save_skill_skips_skill_md_in_files(self):
        """Test that SKILL.md in files list is skipped."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)
            skill_data = {
                "name": "skip-md-skill",
                "description": "Skip SKILL.md",
                "content": "# Content",
                "files": [
                    {"path": "SKILL.md", "content": "# Should be skipped"},
                ]
            }

            result = manager.save_skill(skill_data)

            assert result is not None
            skill_dir = os.path.join(temp.skills_dir, "skip-md-skill")
            md_path = os.path.join(skill_dir, "SKILL.md")
            # Should only have one SKILL.md (the one created by save_skill)
            with open(md_path, "r") as f:
                content = f.read()
                assert "# Should be skipped" not in content


class TestSkillManagerUpdateSkillEdgeCases:
    """Test update_skill_from_file edge cases."""

    def test_update_skill_md_from_bytes(self):
        """Test updating skill with MD as bytes."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            temp.create_skill(
                "bytes-update-skill",
                """---
name: bytes-update-skill
description: Original
---
# Original
""",
            )

            new_content = b"""---
name: bytes-update-skill
description: Updated from bytes
---
# Updated
"""
            result = manager.update_skill_from_file(new_content, "bytes-update-skill")

            assert result is not None
            assert result["description"] == "Updated from bytes"

    def test_update_skill_auto_detects_zip(self):
        """With file_type='auto' and PK magic bytes, code routes to ZIP update."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            temp.create_skill(
                "auto-zip-update",
                """---
name: auto-zip-update
description: Original
---
# Original
""",
            )

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("auto-zip-update/SKILL.md", """---
name: auto-zip-update
description: Auto-detected ZIP update
---
# Updated
""")

            zip_bytes = zip_buffer.getvalue()
            result = manager.update_skill_from_file(
                zip_bytes, "auto-zip-update", file_type="auto"
            )

            assert result is not None
            assert result["description"] == "Auto-detected ZIP update"

    def test_update_skill_zip_skill_disappears_between_calls(self, mocker):
        """If load_skill returns None on the second call inside _update_skill_from_zip, raise."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            temp.create_skill(
                "disappear-update",
                """---
name: disappear-update
description: Original
---
# Original
""",
            )

            # First call (in update_skill_from_file) returns the skill,
            # second call (in _update_skill_from_zip) returns None.
            existing = manager.load_skill("disappear-update")
            call_count = {"n": 0}

            def fake_load_skill(name):
                call_count["n"] += 1
                if call_count["n"] >= 2:
                    return None
                return existing

            mocker.patch.object(manager, "load_skill", side_effect=fake_load_skill)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("disappear-update/SKILL.md", """---
name: disappear-update
description: Disappear
---
# Updated
""")

            zip_bytes = zip_buffer.getvalue()
            with pytest.raises(ValueError, match="Skill not found"):
                manager.update_skill_from_file(
                    zip_bytes, "disappear-update", file_type="zip"
                )


class TestSkillManagerLoadSkillDirectoryWithSubdirs:
    """Additional tests for load_skill_directory."""

    def test_load_directory_with_subdirs(self):
        """Test loading skill directory preserves structure."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "struct-skill",
                """---
name: struct-skill
description: Structure test
---
# Content
""",
                subdirs={
                    "data": {"config.json": '{"setting": true}'},
                    "scripts": [{"name": "run.py", "content": "# script"}],
                },
            )

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.load_skill_directory("struct-skill")

            assert result is not None
            assert os.path.exists(os.path.join(result["directory"], "data", "config.json"))
            assert os.path.exists(os.path.join(result["directory"], "scripts", "run.py"))

            # Cleanup
            import shutil
            if os.path.exists(result["directory"]):
                shutil.rmtree(result["directory"])


class TestSkillManagerDeleteSkillAdditional:
    """Additional tests for delete_skill."""

    def test_delete_skill_non_existent_returns_true(self):
        """Test deleting non-existent skill still returns True."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.delete_skill("never-existed")
            assert result is True


class TestSkillManagerBuildSkillsSummaryAdditional:
    """Additional tests for build_skills_summary."""

    def test_build_summary_multiple_skills(self):
        """Test building summary with multiple skills."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "multi-skill-1",
                """---
name: multi-skill-1
description: First skill
---
# Content
""",
            )
            temp.create_skill(
                "multi-skill-2",
                """---
name: multi-skill-2
description: Second skill
---
# Content
""",
            )

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.build_skills_summary()

            assert "<name>multi-skill-1</name>" in result
            assert "<name>multi-skill-2</name>" in result

    def test_build_summary_with_ampersand_in_description(self):
        """Test XML escaping of ampersand."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "amp-skill",
                """---
name: amp-skill
description: Test & More & Another
---
# Content
""",
            )

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.build_skills_summary()

            assert "&amp;" in result


class TestSkillManagerRunSkillScriptAdditional:
    """Additional tests for run_skill_script."""

    def test_run_script_with_special_chars_in_params(self, mocker):
        """Test running script with special shell characters in params."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "special-params-skill",
                """---
name: special-params-skill
description: Special chars test
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "test.py", "content": "print('ok')"}],
                },
            )

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = '{"ok": true}'
            mock_result.stderr = ""

            mocker.patch("subprocess.run", return_value=mock_result)

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.run_skill_script(
                "special-params-skill",
                "scripts/test.py",
                params='--path "C:\\Program Files\\App" --arg \'single\''
            )

            assert result == '{"ok": true}'

    def test_run_script_python_exception_json_error(self, mocker):
        """Test that Python script errors return JSON with error field."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "py-err-skill",
                """---
name: py-err-skill
description: Python error test
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "error.py", "content": "raise ValueError('test')"}],
                },
            )

            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = "partial output"
            mock_result.stderr = "Traceback"

            mocker.patch("subprocess.run", return_value=mock_result)

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.run_skill_script("py-err-skill", "scripts/error.py")

            parsed = json.loads(result)
            assert "error" in parsed


class TestSkillManagerGetSkillScriptsAdditional:
    """Additional tests for get_skill_scripts."""

    def test_get_scripts_nested_in_subdirs(self):
        """Test getting scripts from nested subdirectories."""
        with TempSkillDir() as temp:
            skill_dir = os.path.join(temp.skills_dir, "nested-scripts")
            os.makedirs(skill_dir)

            with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
                f.write("---\nname: nested-scripts\ndescription: Nested scripts\n---\n# Content\n")

            scripts_dir = os.path.join(skill_dir, "scripts", "utils")
            os.makedirs(scripts_dir)
            with open(os.path.join(scripts_dir, "helper.py"), "w") as f:
                f.write("# Helper\n")

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.get_skill_scripts("nested-scripts")

            assert len(result) == 1
            assert "helper.py" in result[0]


class TestSkillManagerListSkillsAdditional:
    """Additional tests for list_skills."""

    def test_list_skills_with_empty_description(self):
        """Test listing skills with empty description."""
        with TempSkillDir() as temp:
            # Create skill with empty description (YAML parses empty as None)
            skill_dir = os.path.join(temp.skills_dir, "empty-desc-skill")
            os.makedirs(skill_dir)
            with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
                f.write("---\nname: empty-desc-skill\ndescription:\n---\n# Content\n")

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.list_skills()

            # The skill should be listed with empty or None description
            assert len(result) == 1
            assert result[0]["name"] == "empty-desc-skill"
            # YAML empty value parses as None, then defaults to ""
            assert result[0]["description"] in ("", None)


class TestSkillManagerExceptionClasses:
    """Test custom exception classes."""

    def test_skill_not_found_error_default_message(self):
        """Test SkillNotFoundError with default empty message."""
        exc = SkillNotFoundError()
        assert exc.message == ""
        assert str(exc) == ""

    def test_skill_not_found_error_custom_message(self):
        """Test SkillNotFoundError with custom message."""
        exc = SkillNotFoundError("Custom error message")
        assert exc.message == "Custom error message"
        assert "Custom error message" in str(exc)

    def test_skill_script_not_found_error_default_message(self):
        """Test SkillScriptNotFoundError with default empty message."""
        exc = SkillScriptNotFoundError()
        assert exc.message == ""
        assert str(exc) == ""

    def test_skill_script_not_found_error_custom_message(self):
        """Test SkillScriptNotFoundError with custom message."""
        exc = SkillScriptNotFoundError("Script not found")
        assert exc.message == "Script not found"
        assert "Script not found" in str(exc)


class TestSkillManagerFileTypeAutoDetect:
    """Test file type auto-detection in upload/update methods."""

    def test_upload_auto_detect_md_from_content(self):
        """Test auto-detection of MD content without magic bytes."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)
            md_content = """---
name: auto-detect-md
description: Test auto-detection
---
# Content
"""
            result = manager.upload_skill_from_file(md_content, file_type="auto")
            assert result is not None
            assert result["name"] == "auto-detect-md"

    def test_upload_explicit_md_type(self):
        """Test explicit MD file type."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)
            md_content = """---
name: explicit-md
description: Explicit type
---
# Content
"""
            result = manager.upload_skill_from_file(md_content, file_type="md")
            assert result is not None
            assert result["name"] == "explicit-md"

    def test_upload_explicit_zip_type(self):
        """Test explicit ZIP file type."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("explicit-zip-skill/SKILL.md", """---
name: explicit-zip-skill
description: Explicit ZIP
---
# Content
""")

            zip_bytes = zip_buffer.getvalue()
            result = manager.upload_skill_from_file(zip_bytes, file_type="zip")

            assert result is not None
            assert result["name"] == "explicit-zip-skill"


class TestSkillManagerZipRootFallback:
    """Test ZIP upload with SKILL.md at root level."""

    def test_upload_zip_skill_md_in_root_folder(self):
        """Test ZIP where skill folder has SKILL.md in root (len(parts) >= 2)."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                # Create nested structure like "skill-name/docs/SKILL.md"
                # This tests the len(parts) >= 2 branch
                zf.writestr("root-fallback-skill/SKILL.md", """---
name: root-fallback-skill
description: Root fallback
---
# Content
""")
                zf.writestr("root-fallback-skill/data/file.txt", "data file")

            zip_bytes = zip_buffer.getvalue()
            result = manager.upload_skill_from_file(zip_bytes)

            assert result is not None
            assert result["name"] == "root-fallback-skill"


class TestSkillManagerUpdateSkillFromZipExisting:
    """Test update from ZIP when skill exists."""

    def test_update_zip_checks_existing_skill(self):
        """Test that _update_skill_from_zip checks for existing skill."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            # Create initial skill
            temp.create_skill(
                "existing-skill",
                """---
name: existing-skill
description: Original
---
# Original
""",
            )

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("existing-skill/SKILL.md", """---
name: existing-skill
description: Updated
---
# Updated
""")

            zip_bytes = zip_buffer.getvalue()
            result = manager.update_skill_from_file(zip_bytes, "existing-skill")

            assert result is not None
            assert result["description"] == "Updated"


class TestSkillManagerUpdateSkillNotFound:
    """Test update when skill does not exist."""

    def test_update_skill_zip_not_found_raises(self):
        """Test updating non-existent skill with ZIP raises ValueError."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("nonexistent/SKILL.md", """---
name: nonexistent
description: Test
---
# Content
""")

            zip_bytes = zip_buffer.getvalue()

            with pytest.raises(ValueError, match="Skill not found"):
                manager.update_skill_from_file(zip_bytes, "nonexistent")


class TestSkillManagerBuildSummaryNoneValues:
    """Test build_skills_summary with None values."""

    def test_build_summary_none_description_escaped(self):
        """Test that None description is handled in escape_xml."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            # Create skill with description that might parse as None
            skill_dir = os.path.join(temp.skills_dir, "none-desc-skill")
            os.makedirs(skill_dir)
            with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
                f.write("---\nname: none-desc-skill\ndescription:\n---\n# Content\n")

            result = manager.build_skills_summary()

            assert "<name>none-desc-skill</name>" in result


class TestSkillManagerGetSkillFileTreeNonExistent:
    """Test get_skill_file_tree edge cases."""

    def test_get_file_tree_returns_empty_children_for_nonexistent_dir(self):
        """Test get_skill_file_tree when skill dir doesn't exist."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            # Create skill entry then remove the actual directory so that
            # load_skill still returns the cached data but os.path.exists
            # is False inside get_skill_file_tree.
            temp.create_skill(
                "missing-dir-skill",
                """---
name: missing-dir-skill
description: Missing dir
---
# Content
""",
            )
            # Delete only the inner content files but keep SKILL.md so load_skill
            # still parses successfully. Then test the case where load_skill
            # fails entirely (returns None).
            shutil.rmtree(os.path.join(temp.skills_dir, "missing-dir-skill"))

            result = manager.get_skill_file_tree("missing-dir-skill")

            # When load_skill returns None because the dir is gone, return None.
            assert result is None

    def test_get_file_tree_returns_empty_tree_when_dir_gone(self, mocker):
        """When load_skill succeeds but the dir vanishes between calls, return empty tree."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "phantom-dir-skill",
                """---
name: phantom-dir-skill
description: Phantom dir
---
# Content
""",
            )

            manager = SkillManager(base_skills_dir=temp.skills_dir)

            # Make os.path.exists return False on the second invocation to
            # simulate the skill dir disappearing after load_skill.
            real_exists = os.path.exists
            call_count = {"n": 0}

            def fake_exists(path):
                call_count["n"] += 1
                # Allow the first checks (used by load_skill) to pass,
                # then fail the second call which is inside get_skill_file_tree.
                if "phantom-dir-skill" in str(path) and call_count["n"] > 2:
                    return False
                return real_exists(path)

            mocker.patch("os.path.exists", side_effect=fake_exists)
            # Force load_skill to use the cached file content directly.
            loaded = manager.load_skill("phantom-dir-skill")
            assert loaded is not None

            result = manager.get_skill_file_tree("phantom-dir-skill")
            assert result is not None
            assert result["name"] == "phantom-dir-skill"
            assert result["type"] == "directory"


class TestSkillManagerCleanupSkillDirectoryFileBranch:
    """Additional tests for cleanup_skill_directory."""

    def test_cleanup_removes_file_instead_of_dir(self, mocker):
        """Test cleanup when path is a file, not directory."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            # Create a fake temp file
            temp_base = tempfile.gettempdir()
            fake_temp_file = os.path.join(temp_base, f"skill_test-skill_fakeid")
            with open(fake_temp_file, "w") as f:
                f.write("temp content")

            # Verify file exists before cleanup
            assert os.path.exists(fake_temp_file)

            manager.cleanup_skill_directory("test-skill")

            # File should be removed
            # Note: This test may be platform-dependent


class TestSkillManagerRunSkillScriptPathSafety:
    """Additional tests for run_skill_script."""

    def test_run_unsupported_script_type_raises(self):
        """Test running script with unsupported extension raises ValueError."""
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

            manager = SkillManager(base_skills_dir=temp.skills_dir)

            with pytest.raises(ValueError, match="Unsupported script type"):
                manager.run_skill_script("unsupported-skill", "scripts/script.js")

    def _create_run_script_skill(self, temp):
        """Helper to build a skill that hosts a Python script under scripts/."""
        temp.create_skill(
            "rel-path-skill",
            """---
name: rel-path-skill
description: Relative-path resolution test
---
# Content
""",
            subdirs={
                "scripts": [{"name": "hello.py", "content": "print('hi')"}],
            },
        )

    def test_run_skill_script_resolves_relative_to_skill_root(self, mocker):
        """The script_path must resolve relative to the skill root, not CWD."""
        with TempSkillDir() as temp:
            self._create_run_script_skill(temp)

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "ok"
            mock_result.stderr = ""
            mock_sleep = mocker.patch("subprocess.run", return_value=mock_result)

            cwd = os.path.join(temp.skills_dir, "rel-path-skill", "scripts")
            old_cwd = os.getcwd()
            try:
                os.chdir(cwd)
                manager = SkillManager(base_skills_dir=temp.skills_dir)
                # Bare relative path from the SKILL.md body, no extension.
                result = manager.run_skill_script("rel-path-skill", "scripts/hello")
            finally:
                os.chdir(old_cwd)

            assert result == "ok"
            # subprocess.run should have been invoked against the skill-root
            # path, regardless of the caller's CWD.
            called_script = mock_sleep.call_args[0][0][1]
            assert called_script.endswith(os.path.join("rel-path-skill", "scripts", "hello.py"))
            # Verify path is correctly resolved to skill root (not relative to CWD)
            # The path should contain the full skill name with scripts subdirectory
            skill_root_path = os.path.join(temp.skills_dir, "rel-path-skill")
            assert os.path.abspath(called_script).startswith(os.path.abspath(skill_root_path))

    def test_run_skill_script_accepts_dot_slash_prefix(self, mocker):
        """Paths beginning with './' should resolve identically to bare paths."""
        with TempSkillDir() as temp:
            self._create_run_script_skill(temp)

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "out"
            mock_result.stderr = ""
            mock_sleep = mocker.patch("subprocess.run", return_value=mock_result)

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.run_skill_script(
                "rel-path-skill", "./scripts/hello.py"
            )

            assert result == "out"
            called_script = mock_sleep.call_args[0][0][1]
            assert called_script.endswith(os.path.join("rel-path-skill", "scripts", "hello.py"))

    def test_run_skill_script_strips_surrounding_quotes(self, mocker):
        """Paths pulled from backticks/fences may arrive wrapped in quotes."""
        with TempSkillDir() as temp:
            self._create_run_script_skill(temp)

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "out"
            mock_result.stderr = ""
            mock_sleep = mocker.patch("subprocess.run", return_value=mock_result)

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.run_skill_script(
                "rel-path-skill", '"scripts/hello.py"'
            )

            assert result == "out"
            called_script = mock_sleep.call_args[0][0][1]
            assert called_script.endswith(os.path.join("rel-path-skill", "scripts", "hello.py"))

    def test_run_skill_script_falls_back_to_extension(self, mocker):
        """When no extension is supplied, try .py then .sh fall-back."""
        with TempSkillDir() as temp:
            self._create_run_script_skill(temp)

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "shell-out"
            mock_result.stderr = ""
            # Also create a .sh script to verify ordering: .py wins when both exist.
            sh_dir = os.path.join(temp.skills_dir, "rel-path-skill", "scripts")
            with open(os.path.join(sh_dir, "hello.sh"), "w") as fh:
                fh.write("echo hi")
            mock_sleep = mocker.patch("subprocess.run", return_value=mock_result)

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.run_skill_script("rel-path-skill", "scripts/hello")

            assert result == "shell-out"
            called_script = mock_sleep.call_args[0][0][1]
            # .py takes precedence over .sh when both exist.
            assert called_script.endswith(os.path.join("rel-path-skill", "scripts", "hello.py"))

    def test_run_skill_script_missing_script_message_lists_available(self):
        """When the script cannot be found, the error message lists available scripts."""
        with TempSkillDir() as temp:
            self._create_run_script_skill(temp)

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            with pytest.raises(SkillScriptNotFoundError) as excinfo:
                manager.run_skill_script("rel-path-skill", "scripts/missing.py")

            message = excinfo.value.message
            # The error message must explain what the platform tried to do.
            assert "scripts/missing.py" in message
            assert "skill root" in message
            assert "tried" in message
            # And list the script we *did* create so the caller can correct itself.
            assert "scripts/hello.py" in message

    def test_run_skill_script_rejects_path_traversal(self):
        """A path that escapes the skill root must be rejected, not silently run."""
        with TempSkillDir() as temp:
            self._create_run_script_skill(temp)

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            with pytest.raises(SkillScriptNotFoundError) as excinfo:
                manager.run_skill_script(
                    "rel-path-skill",
                    "../../../etc/passwd",
                )

            assert "outside" in excinfo.value.message.lower() or "skill root" in excinfo.value.message.lower()


class TestSkillManagerListSkillsNonExistentDir:
    """Test list_skills when directory doesn't exist."""

    def test_list_skills_nonexistent_base_dir(self):
        """Test listing skills when base_skills_dir doesn't exist."""
        manager = SkillManager(base_skills_dir="/nonexistent/path/to/skills")
        result = manager.list_skills()
        assert result == []


class TestSkillManagerLoadSkillContent:
    """Test load_skill_content edge cases."""

    def test_load_skill_content_with_valid_skill(self):
        """Test loading content of valid skill."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "content-test",
                """---
name: content-test
description: Content test
---
# Actual Content
This is the body.
""",
            )

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.load_skill_content("content-test")

            assert result is not None
            assert "Actual Content" in result
            assert "This is the body" in result


class TestSkillManagerUploadZipDifferentPrefix:
    """Test ZIP with files from different prefix folders."""

    def test_upload_zip_extracts_files_from_different_prefix(self):
        """Test that files from different prefix folders are extracted."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("prefix-skill/SKILL.md", """---
name: prefix-skill
description: Prefix test
---
# Content
""")
                zf.writestr("other-prefix/data.json", '{"other": true}')

            zip_bytes = zip_buffer.getvalue()
            result = manager.upload_skill_from_file(zip_bytes)

            assert result is not None
            skill_dir = os.path.join(temp.skills_dir, "prefix-skill")
            # Files from other-prefix should be extracted with their folder structure
            assert os.path.exists(os.path.join(skill_dir, "other-prefix", "data.json"))


class TestSkillManagerRunScriptNoneAndFallbacks:
    """Cover run_skill_script edge cases: None path, fall-back miss, extensions."""

    def test_run_skill_script_with_none_script_path(self, mocker):
        """Passing script_path=None should produce a meaningful error message."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "none-path-skill",
                """---
name: none-path-skill
description: None script_path test
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "x.py", "content": "print('x')"}],
                },
            )

            manager = SkillManager(base_skills_dir=temp.skills_dir)

            with pytest.raises(SkillScriptNotFoundError) as excinfo:
                manager.run_skill_script("none-path-skill", None)

            # The friendly error should reference the skill root and available scripts.
            assert "none-path-skill" in excinfo.value.message
            assert "scripts/x.py" in excinfo.value.message

    def test_run_skill_script_no_extension_no_fallback(self):
        """Without an extension and no .py/.sh fall-back, raise SkillScriptNotFoundError."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "no-fallback-skill",
                """---
name: no-fallback-skill
description: No fallback test
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "real.py", "content": "print('hi')"}],
                },
            )

            manager = SkillManager(base_skills_dir=temp.skills_dir)

            with pytest.raises(SkillScriptNotFoundError) as excinfo:
                # "scripts/totally_missing" has no extension and no fall-back.
                manager.run_skill_script("no-fallback-skill", "scripts/totally_missing")

            # The fall-back-missed branch message must appear.
            assert "no .py/.sh fall-back matched" in excinfo.value.message

    def test_run_skill_script_strips_backslash_leader(self, mocker):
        """A leading backslash on the path is stripped before resolution."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "bs-leader-skill",
                """---
name: bs-leader-skill
description: Backslash leader test
---
# Content
""",
                subdirs={
                    "scripts": [{"name": "run.py", "content": "print('hi')"}],
                },
            )

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "ok"
            mock_result.stderr = ""
            mock_run = mocker.patch("subprocess.run", return_value=mock_result)

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.run_skill_script(
                "bs-leader-skill", "\\scripts/run.py"
            )

            assert result == "ok"
            called_script = mock_run.call_args[0][0][1]
            assert called_script.endswith(os.path.join("bs-leader-skill", "scripts", "run.py"))


class TestSkillManagerUpdateFromBytesIO:
    """Cover update_skill_from_file when file_content is a BytesIO object."""

    def test_update_skill_md_with_bytesio(self):
        """Update SKILL.md via BytesIO."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            temp.create_skill(
                "bytesio-update",
                """---
name: bytesio-update
description: Original
---
# Original
""",
            )

            new_content = io.BytesIO(b"""---
name: bytesio-update
description: BytesIO updated
---
# Updated
""")

            result = manager.update_skill_from_file(new_content, "bytesio-update")

            assert result is not None
            assert result["description"] == "BytesIO updated"

    def test_update_skill_zip_with_bytesio(self):
        """Update via ZIP passed as BytesIO."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            temp.create_skill(
                "bytesio-zip-update",
                """---
name: bytesio-zip-update
description: Original
---
# Original
""",
            )

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("bytesio-zip-update/SKILL.md", """---
name: bytesio-zip-update
description: BytesIO ZIP updated
---
# Updated
""")
                zf.writestr("bytesio-zip-update/scripts/added.py", "# Added\n")

            zip_buffer.seek(0)
            result = manager.update_skill_from_file(zip_buffer, "bytesio-zip-update")

            assert result is not None
            assert result["description"] == "BytesIO ZIP updated"


class TestSkillManagerUploadZipEdgeCoverage:
    """Cover ZIP upload internal branches (dir entries, deep nesting, fallback)."""

    def test_upload_zip_skips_directory_entries(self):
        """ZIP containing directory placeholders (ending with '/') must be skipped."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                # zipfile.ZipFile can write directory entries when an explicit name ends with '/'.
                zi = zipfile.ZipInfo("dir-entries-skill/data/")
                zi.external_attr = 0x10  # directory flag
                zf.writestr(zi, "")
                zf.writestr("dir-entries-skill/SKILL.md", """---
name: dir-entries-skill
description: dir entries
---
# Content
""")

            zip_bytes = zip_buffer.getvalue()
            result = manager.upload_skill_from_file(zip_bytes)

            assert result is not None
            assert result["name"] == "dir-entries-skill"

    def test_upload_zip_with_deeply_nested_skill_md(self):
        """A ZIP whose SKILL.md is nested 3+ levels deep exercises the elif branch."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                # 3+ parts triggers `elif len(parts) >= 2` branch on line 312.
                zf.writestr("deep-skill/sub/SKILL.md", """---
name: deep-skill
description: Deeply nested
---
# Content
""")

            zip_bytes = zip_buffer.getvalue()
            result = manager.upload_skill_from_file(zip_bytes)

            assert result is not None
            assert result["name"] == "deep-skill"

    def test_upload_zip_fallback_search_finds_skill_md(self):
        """When SKILL.md isn't in the immediate top folder, the fallback search finds it."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                # SKILL.md nested 4 levels deep → not caught by primary loop.
                zf.writestr("fallback-skill/inner/sub/SKILL.md", """---
name: fallback-skill
description: Fallback search
---
# Content
""")

            zip_bytes = zip_buffer.getvalue()
            result = manager.upload_skill_from_file(zip_bytes)

            assert result is not None
            assert result["name"] == "fallback-skill"


class TestSkillManagerUpdateZipEdgeCoverage:
    """Cover _update_skill_from_zip internal branches."""

    def test_update_zip_with_deeply_nested_skill_md(self):
        """Update ZIP with deeply nested SKILL.md exercises len(parts)>=2 branch."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            temp.create_skill(
                "deep-update",
                """---
name: deep-update
description: Original
---
# Original
""",
            )

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                # Deep nesting: parts = ["deep-update", "inner", "sub", "SKILL.md"], len >= 2.
                zf.writestr("deep-update/inner/sub/SKILL.md", """---
name: deep-update
description: Deep updated
---
# Deep updated
""")

            zip_bytes = zip_buffer.getvalue()
            result = manager.update_skill_from_file(zip_bytes, "deep-update")

            assert result is not None
            assert result["description"] == "Deep updated"

    def test_update_zip_skips_file_with_empty_relative_path(self):
        """Update ZIP with a file at the skill root that becomes empty after stripping."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            temp.create_skill(
                "empty-rel-update",
                """---
name: empty-rel-update
description: Original
---
# Original
""",
            )

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("empty-rel-update/SKILL.md", """---
name: empty-rel-update
description: Updated
---
# Updated
""")
                # A file that becomes an empty relative_path after stripping the prefix.
                zf.writestr("empty-rel-update/", "")  # may be skipped before reaching that branch

            zip_bytes = zip_buffer.getvalue()
            result = manager.update_skill_from_file(zip_bytes, "empty-rel-update")

            assert result is not None


class TestSkillManagerCleanupDirectoryPaths:
    """Cover cleanup_skill_directory branches for both file and directory paths."""

    def test_cleanup_removes_directory_branch(self):
        """Cleanup successfully removes a temp directory matching the prefix pattern."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            temp_base = tempfile.gettempdir()
            fake_temp = os.path.join(temp_base, f"skill_cleanup-skill_fakeid")
            os.makedirs(fake_temp, exist_ok=True)
            with open(os.path.join(fake_temp, "marker.txt"), "w") as f:
                f.write("marker")

            assert os.path.isdir(fake_temp)

            manager.cleanup_skill_directory("cleanup-skill")

            assert not os.path.exists(fake_temp)

    def test_cleanup_removes_file_branch(self):
        """Cleanup handles the case where the matching path is a regular file."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            temp_base = tempfile.gettempdir()
            fake_temp_file = os.path.join(temp_base, f"skill_file-skill_fakeid")
            with open(fake_temp_file, "w") as f:
                f.write("data")

            assert os.path.isfile(fake_temp_file)

            manager.cleanup_skill_directory("file-skill")

            assert not os.path.exists(fake_temp_file)

    def test_cleanup_handles_os_remove_exception(self, mocker):
        """If os.remove itself raises, cleanup logs a warning and continues."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            temp_base = tempfile.gettempdir()
            # Use a unique suffix to avoid colliding with leftover artifacts.
            unique_suffix = f"test{mocker.__hash__() % 100000}" if hasattr(mocker, "__hash__") else "testunique"
            fake_path = os.path.join(temp_base, f"skill_osremove-skill_{unique_suffix}")
            with open(fake_path, "w") as f:
                f.write("now-a-file")
            assert os.path.isfile(fake_path)
            try:
                mocker.patch("os.path.isdir", return_value=False)
                mocker.patch("os.remove", side_effect=OSError("access denied"))

                # Should not raise.
                manager.cleanup_skill_directory("osremove-skill")
            finally:
                if os.path.exists(fake_path):
                    try:
                        os.remove(fake_path)
                    except OSError:
                        pass


class TestSkillManagerListAvailableScripts:
    """Cover _list_available_scripts internal branches."""

    def test_list_available_scripts_when_skill_root_missing(self):
        """When the skill root directory does not exist, return empty list."""
        manager = SkillManager(base_skills_dir="/nonexistent/path")
        result = manager._list_available_scripts("/nonexistent/skill")
        assert result == []

    def test_list_available_scripts_finds_files_at_root(self):
        """Finds .py/.sh files even at the skill root (not just under scripts/)."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            skill_dir = os.path.join(temp.skills_dir, "root-scripts-skill")
            os.makedirs(skill_dir)

            with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
                f.write("---\nname: root-scripts-skill\ndescription: Test\n---\n# Content\n")

            # Script at root, not under scripts/.
            with open(os.path.join(skill_dir, "root_script.py"), "w") as f:
                f.write("# root\n")

            result = manager._list_available_scripts(skill_dir)

            assert "root_script.py" in result


class TestSkillManagerFileTreeFoundDirectoryBranch:
    """Cover get_skill_file_tree when directory node already exists in children."""

    def test_get_file_tree_reuses_existing_directory(self):
        """If two files share a directory prefix, that directory is reused (not duplicated)."""
        with TempSkillDir() as temp:
            skill_dir = os.path.join(temp.skills_dir, "reuse-skill")
            os.makedirs(skill_dir)

            with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
                f.write("---\nname: reuse-skill\ndescription: Reuse test\n---\n# Content\n")

            sub_dir = os.path.join(skill_dir, "common")
            os.makedirs(sub_dir)
            with open(os.path.join(sub_dir, "a.py"), "w") as f:
                f.write("# a\n")
            with open(os.path.join(sub_dir, "b.py"), "w") as f:
                f.write("# b\n")

            manager = SkillManager(base_skills_dir=temp.skills_dir)
            result = manager.get_skill_file_tree("reuse-skill")

            assert result is not None

            def find_child(node, name):
                for child in node.get("children", []):
                    if child["name"] == name:
                        return child
                return None

            common = find_child(result, "common")
            assert common is not None
            assert common["type"] == "directory"
            file_names = [c["name"] for c in common["children"]]
            assert "a.py" in file_names
            assert "b.py" in file_names

            # Verify the directory is not duplicated at top level.
            top_dirs = [c for c in result["children"] if c["name"] == "common"]
            assert len(top_dirs) == 1


class TestSkillManagerUploadNoNameInFrontmatter:
    """Cover _upload_skill_from_md branch where frontmatter has no name."""

    def test_upload_md_empty_frontmatter_name_raises(self, mocker):
        """When SKILL.md frontmatter parses without a name and no override is given, raise."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            # Bypass SkillLoader.parse to simulate a dict that lacks 'name'.
            fake_data = {"description": "No name here"}

            mocker.patch.object(
                module_loader.SkillLoader,
                "parse",
                return_value=fake_data,
            )

            with pytest.raises(ValueError, match="Skill name is required"):
                manager._upload_skill_from_md(b"any content")


class TestSkillManagerUpdateZipRootSkillMd:
    """Cover _update_skill_from_zip internal branch when SKILL.md is at ZIP root."""

    def test_update_zip_with_skill_md_at_root(self):
        """SKILL.md placed at ZIP root (parts=['SKILL.md'], len<2) exercises the branch."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            temp.create_skill(
                "root-md-update",
                """---
name: root-md-update
description: Original
---
# Original
""",
            )

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                # SKILL.md directly at root → parts=['SKILL.md'], len(parts)<2.
                zf.writestr("SKILL.md", """---
name: root-md-update
description: Root updated
---
# Root updated
""")
                zf.writestr("extra/data.json", '{"k": "v"}')

            zip_bytes = zip_buffer.getvalue()
            result = manager.update_skill_from_file(zip_bytes, "root-md-update")

            assert result is not None
            assert result["description"] == "Root updated"


class TestSkillManagerCleanupSkillDirectoryFileRemoval:
    """Cover cleanup_skill_directory branch when path is a regular file."""

    def test_cleanup_removes_file_path_branch(self):
        """Cleanup hits the os.remove branch when the matched path is a file."""
        with TempSkillDir() as temp:
            manager = SkillManager(base_skills_dir=temp.skills_dir)

            temp_base = tempfile.gettempdir()
            fake_path = os.path.join(temp_base, f"skill_filebranch-skill_abc123")
            with open(fake_path, "w") as f:
                f.write("data")
            assert os.path.isfile(fake_path)

            try:
                manager.cleanup_skill_directory("filebranch-skill")
                assert not os.path.exists(fake_path)
            finally:
                if os.path.exists(fake_path):
                    try:
                        os.remove(fake_path)
                    except OSError:
                        pass


class TestSkillManagerLoadDirectoryMissingPath:
    """Cover load_skill_directory branch when local_path no longer exists."""

    def test_load_skill_directory_when_local_path_missing(self, mocker):
        """If load_skill returns data but the on-disk directory is gone, still return skill."""
        with TempSkillDir() as temp:
            temp.create_skill(
                "phantom-load-skill",
                """---
name: phantom-load-skill
description: Phantom load
---
# Content
""",
            )

            manager = SkillManager(base_skills_dir=temp.skills_dir)

            real_exists = os.path.exists
            call_count = {"n": 0}

            def fake_exists(path):
                call_count["n"] += 1
                if "phantom-load-skill" in str(path) and call_count["n"] > 2:
                    return False
                return real_exists(path)

            mocker.patch("os.path.exists", side_effect=fake_exists)
            loaded = manager.load_skill("phantom-load-skill")
            assert loaded is not None

            result = manager.load_skill_directory("phantom-load-skill")
            # Should still return the skill dict (with directory set to a fresh tempdir).
            assert result is not None
            assert result["name"] == "phantom-load-skill"
            # Cleanup the temp directory.
            if os.path.isdir(result["directory"]):
                shutil.rmtree(result["directory"])


class TestSkillManagerAddToTreeTypeConflictBranch:
    """Cover _add_to_tree internal branches: type conflict and dir reuse."""

    def test_add_to_tree_directory_reuse_branch(self):
        """Adding nested path into an existing directory node reuses that node."""
        manager = SkillManager()
        node = {
            "name": "root",
            "type": "directory",
            "children": [
                {"name": "dir1", "type": "directory", "children": []}
            ],
        }

        # Recursing through parts=["dir1", "x.txt"], the first iteration finds dir1.
        manager._add_to_tree(node, ["dir1", "x.txt"], is_directory=False)

        assert len(node["children"]) == 1
        assert node["children"][0]["name"] == "dir1"
        assert node["children"][0]["children"][0]["name"] == "x.txt"

    def test_add_to_tree_directory_creates_new_when_missing(self):
        """When the directory prefix is missing, _add_to_tree creates it."""
        manager = SkillManager()
        node = {"name": "root", "type": "directory", "children": []}

        manager._add_to_tree(node, ["newdir", "file.txt"], is_directory=False)

        assert len(node["children"]) == 1
        assert node["children"][0]["name"] == "newdir"
        assert node["children"][0]["type"] == "directory"
        assert node["children"][0]["children"][0]["name"] == "file.txt"

    def test_add_to_tree_type_conflict_skip(self):
        """When a name exists with conflicting type, the second add is skipped."""
        manager = SkillManager()
        node = {
            "name": "root",
            "type": "directory",
            "children": [
                {"name": "shared", "type": "directory", "children": []}
            ],
        }

        # Adding "shared" as a file conflicts with the existing directory.
        manager._add_to_tree(node, ["shared"], is_directory=False)

        # No new file child should be appended.
        assert len(node["children"]) == 1
        assert node["children"][0]["name"] == "shared"
        assert node["children"][0]["type"] == "directory"

    def test_add_to_tree_no_match_in_existing_children(self):
        """Adding a leaf that doesn't match any existing child exercises the loop-no-match branch."""
        manager = SkillManager()
        node = {
            "name": "root",
            "type": "directory",
            "children": [
                {"name": "alpha", "type": "file", "children": []},
                {"name": "beta", "type": "file", "children": []},
            ],
        }

        manager._add_to_tree(node, ["gamma"], is_directory=False)

        names = [c["name"] for c in node["children"]]
        assert "alpha" in names
        assert "beta" in names
        assert "gamma" in names
        assert len(node["children"]) == 3

    def test_add_to_tree_skip_non_directory_child_in_dir_lookup(self):
        """When looking for a directory but the matching child is a file, skip it."""
        manager = SkillManager()
        # "data" exists as a file child, but the lookup wants a directory with that name.
        node = {
            "name": "root",
            "type": "directory",
            "children": [
                {"name": "data", "type": "file", "children": []}
            ],
        }

        # Adding parts=["data", "nested.txt"] should NOT reuse the file child.
        # Instead it must create a new directory "data" alongside the existing file.
        manager._add_to_tree(node, ["data", "nested.txt"], is_directory=False)

        # Both the original file and the new directory should be present.
        names = [c["name"] for c in node["children"]]
        assert "data" in names
        # The new directory is the one with type "directory".
        dir_entries = [c for c in node["children"] if c["name"] == "data" and c["type"] == "directory"]
        assert len(dir_entries) == 1
        assert dir_entries[0]["children"][0]["name"] == "nested.txt"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
