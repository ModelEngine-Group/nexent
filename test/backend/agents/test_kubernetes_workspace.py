# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import os
from pathlib import Path

import pytest
from runtime.sandbox_workspace import KubernetesWorkspace

from nexent.core.agents.sandbox_contracts import SandboxOwner


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    if os.name == 'posix':
        monkeypatch.setattr('runtime.sandbox_workspace.os.geteuid', lambda: 0)
        monkeypatch.setattr('runtime.sandbox_workspace.os.fchown', lambda *args, **kwargs: None)
    owner = SandboxOwner('release', 'namespace', 'runtime', 'uid-a', '10.0.0.1', 'epoch')
    return KubernetesWorkspace(tmp_path, owner, execution_gid=1000)


def test_owner_tenant_user_and_run_are_unambiguous(workspace):
    run_id = 'a' * 32
    first = workspace.run_path('tenant/a', 'user:a', run_id)
    second = workspace.run_path('tenant_a', 'user:a', run_id)
    assert first != second
    assert first.name == run_id and first.is_relative_to(workspace.owner_root)
    assert workspace.owner_root == workspace.root / 'owners' / 'uid-a'
    assert not first.is_relative_to(workspace.control_root)


@pytest.mark.parametrize('run_id', ['../bad', 'a' * 31, 'A' * 32, '', 'a/b'])
def test_run_id_is_a_validated_internal_identity(workspace, run_id):
    with pytest.raises(ValueError):
        workspace.run_path('tenant', 'user', run_id)


def test_prepare_does_not_widen_or_follow_output_symlinks(workspace, tmp_path):
    run = workspace.prepare_run('tenant', 'user', 'a' * 32)
    assert all((run / name).is_dir() for name in ('inputs', 'outputs', 'tmp', '.skills'))
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'sentinel').write_text('keep')
    try:
        (run / 'outputs' / 'link').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Windows symlink creation is unavailable')
    workspace.prepare_run('tenant', 'user', 'a' * 32)
    assert (outside / 'sentinel').read_text() == 'keep'


@pytest.mark.skipif(os.name != 'posix', reason='POSIX file descriptor permissions')
def test_prepare_does_not_require_path_chmod_nofollow(workspace, monkeypatch):
    chmod = Path.chmod

    def limited_chmod(path, mode, *, follow_symlinks=True):
        if not follow_symlinks:
            raise NotImplementedError('chmod: follow_symlinks unavailable on this platform')
        return chmod(path, mode)

    monkeypatch.setattr(Path, 'chmod', limited_chmod)
    run = workspace.prepare_run('tenant', 'user', 'a' * 32)
    assert (run / 'outputs').stat().st_mode & 0o2777 == 0o2770


def test_existing_symlink_run_root_is_rejected(workspace, tmp_path):
    run = workspace.run_path('tenant', 'user', 'a' * 32)
    run.parent.mkdir(parents=True)
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        run.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Windows symlink creation is unavailable')
    with pytest.raises(ValueError, match='symlink'):
        workspace.prepare_run('tenant', 'user', 'a' * 32)


def test_workspace_pvc_subpath_is_explicit(workspace):
    assert workspace.volume_subpath(Path(workspace.root).parent) == workspace.root.name + '/owners/uid-a'
    with pytest.raises(ValueError):
        workspace.volume_subpath(workspace.root / 'foreign')
