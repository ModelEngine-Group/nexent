# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import pytest
from runtime.sandbox_workspace import KubernetesWorkspace

from nexent.core.agents.sandbox_contracts import SandboxOwner


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
    workspace.cleanup_skills(str(run), 'c' * 24)
    assert (parent / 'run.sh').exists() and not child.exists()
    assert workspace.stage_skill(str(source), str(run), 'b' * 24) == parent
    with pytest.raises(ValueError):
        workspace.cleanup_skills(str(run), '../foreign')
