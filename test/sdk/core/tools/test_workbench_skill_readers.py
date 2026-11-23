"""Request-scoped Skill reader authorization regressions."""

import json

import pytest

from nexent.core.tools.read_skill_config_tool import ReadSkillConfigTool
from nexent.core.tools.read_skill_md_tool import ReadSkillMdTool
from nexent.core.tools.run_skill_script_tool import RunSkillScriptTool


@pytest.mark.parametrize("name", ["cancelled", "", "../mounted"])
def test_runtime_md_reader_denies_unselected_skills_before_loading(mocker, name):
    reader = ReadSkillMdTool(authorized_skill_names=["mounted"])
    manager = mocker.patch.object(reader, "_get_skill_manager")
    assert reader.execute(name) == "Skill access is not authorized"
    manager.assert_not_called()


def test_runtime_md_reader_rejects_paths_outside_selected_root(tmp_path):
    reader = ReadSkillMdTool(authorized_skill_names=["mounted"])
    content, found = reader._read_skill_file(str(tmp_path / "mounted"), "../private.txt")
    assert not found
    assert content == "File access is not authorized"


def test_runtime_config_reader_uses_isolated_snapshot_without_disk(mocker):
    values = {"mounted": {"region": "CN", "nested": {"value": 1}}}
    reader = ReadSkillConfigTool(config_overrides=values, authorized_skill_names=["mounted"])
    values["mounted"]["nested"]["value"] = 99
    file_open = mocker.patch("builtins.open", side_effect=AssertionError("No disk reads for resolved config"))
    assert json.loads(reader.execute("mounted")) == {"region": "CN", "nested": {"value": 1}}
    assert reader.execute("cancelled") == "[Error] Skill access is not authorized"
    assert ReadSkillConfigTool(authorized_skill_names=[]).execute("mounted") == "[Error] Skill access is not authorized"
    file_open.assert_not_called()


def test_runtime_reader_and_runner_resolve_the_same_isolated_snapshot(tmp_path):
    """UT-BE-WB-011: reader, runner and sandbox archive share the frozen files."""
    import io
    import tarfile
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from nexent.core.agents.sandbox import SandboxSkillScriptRunner

    snapshot_root = tmp_path / "snapshot"
    skill_root = snapshot_root / "tenant" / "mounted"
    (skill_root / "scripts").mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\nname: mounted\ndescription: Frozen guide\n---\nSnapshot body",
        encoding="utf-8",
    )
    (skill_root / "scripts" / "run.py").write_text(
        "print('snapshot')",
        encoding="utf-8",
    )
    reader = ReadSkillMdTool(
        local_skills_dir=str(snapshot_root),
        tenant_id="tenant",
        authorized_skill_names=["mounted"],
        isolated_skills_root=True,
    )
    runner = RunSkillScriptTool(
        local_skills_dir=str(snapshot_root),
        tenant_id="tenant",
        authorized_skill_names=["mounted"],
        isolated_skills_root=True,
    )

    assert "Snapshot body" in reader.execute("mounted")
    skill_dir, script, relative = runner._get_skill_manager().resolve_skill_script(
        "mounted",
        "scripts/run.py",
        tenant_id="tenant",
    )
    assert skill_dir == str(skill_root.resolve())
    assert script == str((skill_root / "scripts" / "run.py").resolve())
    assert relative.replace("\\", "/") == "scripts/run.py"

    container = MagicMock()
    container.exec_run.return_value = SimpleNamespace(exit_code=0, output=b"")
    container.put_archive.return_value = True
    sandbox = SandboxSkillScriptRunner(
        SimpleNamespace(container=container, _nexent_backend="docker"),
        workspace_path=str(tmp_path / "workspace"),
    )
    staged, _ = sandbox._stage_skill(
        runner._get_skill_manager(), "mounted", "scripts/run.py", "tenant", "/workspace/skills",
    )
    sandbox._stage_skill(
        runner._get_skill_manager(), "mounted", "scripts/run.py", "tenant", "/workspace/skills",
    )
    container.put_archive.assert_called_once()
    assert staged.startswith("/workspace/skills/mounted-")
    archive_bytes = container.put_archive.call_args.args[1]
    with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
        members = {item.name: item for item in archive.getmembers() if item.isfile()}
        script_name = next(name for name in members if name.endswith("/scripts/run.py"))
        guide_name = next(name for name in members if name.endswith("/SKILL.md"))
        assert archive.extractfile(script_name).read() == b"print('snapshot')"
        assert b"Snapshot body" in archive.extractfile(guide_name).read()
    assert any(call.args[0][:3] == ["chmod", "-R", "a-w"] for call in container.exec_run.call_args_list)
