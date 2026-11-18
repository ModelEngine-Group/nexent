# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import os
import stat
from dataclasses import replace

import pytest
from runtime.sandbox_workspace import KubernetesWorkspace

from nexent.core.agents.sandbox_contracts import SandboxOwner


@pytest.fixture(autouse=True)
def trusted_runtime_identity(monkeypatch):
    if os.name == 'posix':
        monkeypatch.setattr('runtime.sandbox_workspace.os.geteuid', lambda: 0)
        monkeypatch.setattr('runtime.sandbox_workspace.os.fchown', lambda *args, **kwargs: None)


@pytest.fixture
def restore_workspace_write_permission(tmp_path):
    yield
    if os.name == 'posix':
        # Sealed directories must be writable by the test user for tmp_path cleanup.
        for path in tmp_path.rglob('*'):
            if not path.is_symlink() and path.is_dir():
                mode = stat.S_IMODE(path.stat().st_mode)
                if not mode & stat.S_IWUSR:
                    path.chmod(mode | stat.S_IWUSR)


@pytest.mark.usefixtures('restore_workspace_write_permission')
def test_staging_normalizes_only_private_shell_copy_and_child_cleanup_preserves_parent(tmp_path, monkeypatch):
    # Identity hashing has separate tests; keep filesystem fixture paths short on Windows.
    monkeypatch.setattr('runtime.sandbox_workspace._business_key', lambda value: value)
    owner = SandboxOwner('release', 'namespace', 'runtime', 'uid', '10.0.0.1', 'epoch')
    workspace = KubernetesWorkspace(tmp_path / 'workspace', owner, execution_gid=1000)
    run = workspace.prepare_run('tenant', 'user', 'a' * 32)
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'run.sh').write_bytes(b'echo hello\r\n')
    parent = workspace.stage_skill(str(source), str(run), 'b' * 24)
    child = workspace.stage_skill(str(source), str(run), 'c' * 24)
    assert (source / 'run.sh').read_bytes() == b'echo hello\r\n'
    assert (parent / 'run.sh').read_bytes() == (child / 'run.sh').read_bytes() == b'echo hello\n'
    if os.name == 'posix':
        assert child.stat().st_mode & 0o777 == 0o550
        # Emulate the trusted Runtime's ability to remove the read-only staged files.
        child.chmod(0o750)
    workspace.cleanup_skills(str(run), 'c' * 24)
    assert (parent / 'run.sh').exists() and not child.exists()
    assert workspace.stage_skill(str(source), str(run), 'b' * 24) == parent
    with pytest.raises(ValueError):
        workspace.cleanup_skills(str(run), '../foreign')


@pytest.mark.usefixtures('restore_workspace_write_permission')
def test_sealing_materials_keeps_outputs_writable_and_never_follows_links(tmp_path, monkeypatch):
    monkeypatch.setattr('runtime.sandbox_workspace._business_key', lambda value: value)
    owner = SandboxOwner('release', 'ns', 'runtime', 'uid', '10.0.0.1', 'epoch')
    workspace = KubernetesWorkspace(tmp_path / 'work', owner, execution_gid=1000)
    run = workspace.prepare_run('tenant', 'user', 'a' * 32)
    material = run / 'inputs' / 'source.txt'
    material.write_text('trusted input')
    nested = run / '.skills' / 'nested'
    nested.mkdir()
    (nested / 'SKILL.md').write_text('trusted skill')
    output = run / 'outputs' / 'generated.txt'
    output.write_text('writable output')
    output_mode = output.stat().st_mode
    workspace.seal_materials(run)
    assert material.read_text() == 'trusted input'
    assert output.stat().st_mode == output_mode
    if os.name == 'posix':
        assert material.stat().st_mode & 0o777 == 0o440
        assert nested.stat().st_mode & 0o777 == 0o550
        assert (run / 'outputs').stat().st_mode & 0o2770 == 0o2770
    with pytest.raises(ValueError):
        workspace.seal_materials(tmp_path / 'foreign')


@pytest.mark.parametrize('value', ['', 7, 'x' * 4097])
def test_invalid_business_identity_cannot_select_a_workspace(value):
    from runtime.sandbox_workspace import _business_key
    with pytest.raises(ValueError):
        _business_key(value)


@pytest.mark.parametrize('gid', [-1, True])
def test_workspace_rejects_invalid_execution_group(tmp_path, gid):
    owner = SandboxOwner('release', 'ns', 'runtime', 'uid', '10.0.0.1', 'epoch')
    with pytest.raises(ValueError, match='execution group'):
        KubernetesWorkspace(tmp_path, owner, execution_gid=gid)
    with pytest.raises(ValueError, match='UID path'):
        KubernetesWorkspace(tmp_path, replace(owner, pod_uid='bad/uid'), execution_gid=1000)


def test_staging_rejects_untrusted_source_and_run_identity(tmp_path, monkeypatch):
    monkeypatch.setattr('runtime.sandbox_workspace._business_key', lambda value: value)
    owner = SandboxOwner('release', 'ns', 'runtime', 'uid', '10.0.0.1', 'epoch')
    workspace = KubernetesWorkspace(tmp_path / 'work', owner, execution_gid=1000)
    run = workspace.prepare_run('tenant', 'user', 'a' * 32)
    source = tmp_path / 'source.txt'
    source.write_text('not a directory')
    with pytest.raises(ValueError, match='invocation identity'):
        workspace.stage_skill(str(source), str(run), '../other')
    with pytest.raises(ValueError, match='run workspace'):
        workspace.stage_skill(str(source), str(run.parent / 'invalid'), 'b' * 24)
    with pytest.raises(ValueError, match='not a directory'):
        workspace.stage_skill(str(source), str(run), 'b' * 24)


@pytest.mark.skipif(os.name != 'posix', reason='Linux root and setgid permission boundary')
def test_pvc_setgid_is_preserved_and_untrusted_runtime_cannot_prepare(tmp_path, monkeypatch):
    owner = SandboxOwner('release', 'ns', 'runtime', 'uid', '10.0.0.1', 'epoch')
    root = tmp_path / 'work'
    root.mkdir()
    root.chmod(0o2770)
    workspace = KubernetesWorkspace(root, owner, execution_gid=1000)
    workspace.prepare_run('tenant', 'user', 'a' * 32)
    assert root.stat().st_mode & 0o2770 == 0o2770
    monkeypatch.setattr('runtime.sandbox_workspace.os.geteuid', lambda: 1000)
    with pytest.raises(RuntimeError, match='trusted root Runtime'):
        workspace.prepare_run('tenant', 'user', 'b' * 32)
