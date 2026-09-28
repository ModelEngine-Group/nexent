"""Unit tests for bounded Workbench Skill file snapshots."""

import pytest

from services import workbench_service


def test_ut_be_wb_011_capture_freezes_files_and_cleans_temporary_copy(
    tmp_path,
    mocker,
):
    source = tmp_path / "skill_invoice-skill_test"
    (source / "scripts").mkdir(parents=True)
    (source / "SKILL.md").write_bytes(b"# Frozen")
    (source / "scripts" / "run.py").write_bytes(b"print('frozen')")
    mocker.patch.object(
        workbench_service.SkillService,
        "load_skill_directory",
        return_value={"directory": str(source)},
    )
    mocker.patch.object(
        workbench_service.tempfile,
        "gettempdir",
        return_value=str(tmp_path),
    )

    snapshot = workbench_service._capture_skill_file_snapshot(
        "invoice-skill",
        "tenant",
    )

    assert dict(snapshot) == {
        "SKILL.md": b"# Frozen",
        "scripts/run.py": b"print('frozen')",
    }
    assert not source.exists()


def test_ut_be_wb_011_capture_requires_skill_guide(tmp_path, mocker):
    source = tmp_path / "skill_broken_test"
    source.mkdir()
    (source / "data.txt").write_bytes(b"data")
    mocker.patch.object(
        workbench_service.SkillService,
        "load_skill_directory",
        return_value={"directory": str(source)},
    )
    mocker.patch.object(
        workbench_service.tempfile,
        "gettempdir",
        return_value=str(tmp_path),
    )

    with pytest.raises(
        workbench_service.WorkbenchError,
        match="RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE",
    ):
        workbench_service._capture_skill_file_snapshot("broken", "tenant")
    assert not source.exists()
