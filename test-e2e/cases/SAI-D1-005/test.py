"""SAI-D1-005: case-local preserved component regression."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from nexent.core.agents import sandbox
from nexent.core.agents.nexent_agent import NexentAgent
from shared.sai_component import (
    ORIGINAL_SANDBOX_CLEANUP as ORIGINAL_SANDBOX_CLEANUP,
)
from shared.sai_component import (
    manager as manager,
)
from shared.sai_component import (
    setup_factory as setup_factory,
)


def test_SAI_D1_005_shared_skill_cleanup(setup_factory, monkeypatch, tmp_path):
    import shutil

    factory, child, _, _, _ = setup_factory
    factory.workspace_path = str(tmp_path)
    script = tmp_path / 'skills' / 'sample' / 'run.py'
    script.parent.mkdir(parents=True)
    script.write_text('print(1)')
    removals = []

    def command(argv, **kwargs):
        if argv[:3] == ['rm', '-rf', '--']:
            removals.append(argv[3])
            assert Path(argv[3]) == tmp_path / 'skills'
            shutil.rmtree(argv[3], ignore_errors=True)
        return SimpleNamespace(exit_code=0, output=b'')

    executor = SimpleNamespace(container=SimpleNamespace(exec_run=command), _nexent_backend='docker')
    root_runner = sandbox.SandboxSkillScriptRunner(executor, workspace_path=str(tmp_path))
    root_runner._staged_skills['sample'] = str(script.parent)
    factory._sandbox_skill_runners.append(root_runner)

    def initialize(owner):
        owner._sandbox_skill_runners.append(sandbox.SandboxSkillScriptRunner(executor, workspace_path=str(tmp_path)))

    monkeypatch.setattr(NexentAgent, '_initialize_sandbox_workspaces', initialize)
    monkeypatch.setattr(NexentAgent, '_cleanup_sandbox', ORIGINAL_SANDBOX_CLEANUP)
    monkeypatch.setattr(sandbox, 'cleanup_executor', lambda *args, **kwargs: None)
    child(task='LEFT')
    assert script.exists() and not removals
    assert script.parent == tmp_path / 'skills' / 'sample'
    child(task='RIGHT')
    assert script.read_text() == 'print(1)' and not removals
    factory._close_subagent_invocations()
    factory._cleanup_sandbox()
    assert not script.exists() and removals


pytestmark = [pytest.mark.case_id("SAI-D1-005"), pytest.mark.stage("D1")]
