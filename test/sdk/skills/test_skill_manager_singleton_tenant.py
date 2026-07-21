import os

import pytest
from smolagents import BaseTool

from nexent.skills import SkillManager
from nexent.core.tools.read_skill_config_tool import ReadSkillConfigTool
from nexent.core.tools.read_skill_md_tool import ReadSkillMdTool
from nexent.core.tools.run_skill_script_tool import RunSkillScriptTool
from nexent.core.tools.write_skill_file_tool import WriteSkillFileTool


@pytest.fixture(autouse=True)
def reset_skill_manager_singleton():
    SkillManager._reset_instance_for_testing()
    yield
    SkillManager._reset_instance_for_testing()


def test_skill_manager_is_process_singleton_with_immutable_root(tmp_path):
    manager = SkillManager(str(tmp_path))
    same_manager = SkillManager(str(tmp_path / "ignored"))

    assert same_manager is manager
    assert manager.base_skills_dir == os.path.abspath(tmp_path)
    assert not hasattr(manager, "local_skills_dir")
    assert not hasattr(manager, "tenant_id")


def test_tenant_paths_are_isolated_and_reject_escape(tmp_path):
    manager = SkillManager(str(tmp_path))

    tenant_a = manager.resolve_tenant_dir(tenant_id="Tenant-A")
    tenant_b = manager.resolve_tenant_dir(tenant_id="Tenant-B")

    assert tenant_a == os.path.join(os.path.abspath(tmp_path), "Tenant-A")
    assert tenant_b == os.path.join(os.path.abspath(tmp_path), "Tenant-B")
    assert tenant_a != tenant_b

    with pytest.raises(ValueError, match="outside"):
        manager.resolve_tenant_dir(tenant_id="../escape")
    with pytest.raises(ValueError, match="non-empty"):
        manager.resolve_tenant_dir(tenant_id="")
    with pytest.raises(ValueError, match="outside"):
        manager.resolve_skill_dir("../other-tenant/skill", tenant_id="Tenant-A")


def test_skill_operations_require_and_use_call_tenant(tmp_path):
    manager = SkillManager(str(tmp_path))
    skill = {"name": "shared-name", "description": "A", "content": "tenant A"}

    manager.save_skill(skill, tenant_id="Tenant-A")
    manager.save_skill({**skill, "description": "B", "content": "tenant B"}, tenant_id="Tenant-B")

    assert manager.load_skill("shared-name", tenant_id="Tenant-A")["description"] == "A"
    assert manager.load_skill("shared-name", tenant_id="Tenant-B")["description"] == "B"

    with pytest.raises(TypeError):
        manager.load_skill("shared-name")


def test_agent_tools_share_manager_without_sharing_tenant_context(tmp_path):
    manager = SkillManager(str(tmp_path))
    for tenant_id, marker in (("Tenant-A", "A"), ("Tenant-B", "B")):
        manager.save_skill(
            {
                "name": "shared-skill",
                "description": marker,
                "content": marker,
                "files": [
                    {"path": "scripts/show.py", "content": f"print('{marker}')"},
                    {"path": "config.yaml", "content": f"marker: {marker}\n"},
                ],
            },
            tenant_id=tenant_id,
        )

    run_a = RunSkillScriptTool(str(tmp_path), agent_id=1, tenant_id="Tenant-A")
    run_b = RunSkillScriptTool(str(tmp_path), agent_id=2, tenant_id="Tenant-B")
    read_a = ReadSkillMdTool(str(tmp_path), agent_id=1, tenant_id="Tenant-A")
    read_b = ReadSkillMdTool(str(tmp_path), agent_id=2, tenant_id="Tenant-B")
    config_a = ReadSkillConfigTool(str(tmp_path), agent_id=1, tenant_id="Tenant-A")
    config_b = ReadSkillConfigTool(str(tmp_path), agent_id=2, tenant_id="Tenant-B")
    write_a = WriteSkillFileTool(str(tmp_path), agent_id=1, tenant_id="Tenant-A")

    assert all(
        isinstance(tool, BaseTool)
        for tool in (run_a, run_b, read_a, read_b, config_a, config_b, write_a)
    )

    assert run_a._get_skill_manager() is run_b._get_skill_manager() is manager
    assert run_a.execute("shared-skill", "scripts/show.py").strip() == "A"
    assert run_b.execute("shared-skill", "scripts/show.py").strip() == "B"
    assert "A" in read_a.execute("shared-skill")
    assert "B" in read_b.execute("shared-skill")
    assert '"A"' in config_a.execute("shared-skill")
    assert '"B"' in config_b.execute("shared-skill")

    assert "Successfully wrote" in write_a.execute("shared-skill", "tenant.txt", "only A")
    assert os.path.isfile(tmp_path / "Tenant-A" / "shared-skill" / "tenant.txt")
    assert not os.path.exists(tmp_path / "Tenant-B" / "shared-skill" / "tenant.txt")
