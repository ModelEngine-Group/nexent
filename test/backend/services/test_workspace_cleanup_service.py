from services.workspace_cleanup_service import cleanup_orphaned_agent_workspaces


def test_cleanup_orphaned_agent_workspaces_removes_only_run_directories(tmp_path):
    root = tmp_path / "workdir"
    user_dir = root / "user-1"
    valid_run = user_dir / ("a" * 32)
    invalid_run = user_dir / "keep-this-directory"
    (valid_run / "outputs").mkdir(parents=True)
    (valid_run / "outputs" / "result.txt").write_text("temporary", encoding="utf-8")
    invalid_run.mkdir()
    (invalid_run / "keep.txt").write_text("persistent", encoding="utf-8")

    removed = cleanup_orphaned_agent_workspaces(str(root))

    assert removed == 1
    assert not valid_run.exists()
    assert invalid_run.exists()


def test_cleanup_orphaned_agent_workspaces_removes_empty_user_directory(tmp_path):
    root = tmp_path / "workdir"
    user_dir = root / "user-1"
    (user_dir / ("b" * 32)).mkdir(parents=True)

    removed = cleanup_orphaned_agent_workspaces(str(root))

    assert removed == 1
    assert not user_dir.exists()
    assert root.exists()


def test_cleanup_orphaned_agent_workspaces_ignores_missing_root(tmp_path):
    assert cleanup_orphaned_agent_workspaces(str(tmp_path / "missing")) == 0
