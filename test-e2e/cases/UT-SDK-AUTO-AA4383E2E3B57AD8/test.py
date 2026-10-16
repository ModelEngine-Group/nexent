from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from nexent.core.agents.sandbox import _scan_shell_calls
from nexent.core.tools.run_skill_script_tool import (
    RunSkillScriptTool,
    SkillScriptExecutionError,
)

CASE_ID = 'UT-SDK-AUTO-AA4383E2E3B57AD8'


def _make_tool(authorized_skill_names=None, execution_backend=None):
    tool = RunSkillScriptTool(
        local_skills_dir=None,
        agent_id=42,
        tenant_id='tenant-a',
        authorized_skill_names=authorized_skill_names,
        execution_backend=execution_backend,
    )
    tool.skill_manager = Mock()
    return tool


@pytest.mark.stage('D1')
@pytest.mark.case_id(CASE_ID)
def test_run_skill_script_source_auth_and_shell_guard():
    backend = Mock(return_value='ok')
    tool = _make_tool(execution_backend=backend)
    assert tool.execute('allowed-skill', 'scripts/analyze.py', None, source='skill') == 'ok'
    assert 'source' not in backend.call_args.kwargs

    workspace_backend = Mock(return_value='ok')
    workspace_tool = _make_tool(execution_backend=workspace_backend)
    assert workspace_tool.execute('allowed-skill', 'outputs/analyze.py', None, source='workspace') == 'ok'
    assert workspace_backend.call_args.kwargs['source'] == 'workspace'

    invalid_backend = Mock(return_value='ok')
    invalid_tool = _make_tool(execution_backend=invalid_backend)
    invalid_message = invalid_tool.execute('allowed-skill', 'scripts/analyze.py', None, source='invalid')
    assert invalid_message.startswith('[UnexpectedError]')
    assert 'ValueError' in invalid_message
    invalid_backend.assert_not_called()
    invalid_tool.skill_manager.assert_not_called()
    assert not invalid_tool.skill_manager.mock_calls
    assert 'source must be either' in invalid_message
    assert 'skill' in invalid_message
    assert 'workspace' in invalid_message

    auth_backend = Mock(return_value='ok')
    auth_tool = _make_tool(authorized_skill_names={'allowed-skill'}, execution_backend=auth_backend)
    auth_message = auth_tool.execute('blocked-skill', 'scripts/analyze.py', None, source='skill')
    assert auth_message.startswith('[UnexpectedError]')
    assert 'PermissionError' in auth_message
    assert 'not enabled for agent' in auth_message
    auth_backend.assert_not_called()
    assert not auth_tool.skill_manager.mock_calls

    assert auth_tool.execute('allowed-skill', 'scripts/analyze.py', None, source='skill') == 'ok'
    assert auth_backend.called
    assert auth_backend.call_args.kwargs['skill_name'] == 'allowed-skill'
    assert auth_backend.call_args.kwargs['manager'] is auth_tool.skill_manager

    error_tool = _make_tool(execution_backend=Mock(return_value=json.dumps({'error': 'boom'})))
    with pytest.raises(SkillScriptExecutionError) as error_exc:
        error_tool.execute('allowed-skill', 'scripts/analyze.py', None, source='skill')
    assert 'boom' in str(error_exc.value)
    assert '[UnexpectedError]' not in str(error_exc.value)

    no_backend_tool = _make_tool()
    ws_message = no_backend_tool.execute('allowed-skill', 'outputs/analyze.py', None, source='workspace')
    assert ws_message.startswith('[UnexpectedError]')
    assert 'RuntimeError' in ws_message
    assert 'Workspace scripts require an available Docker sandbox execution backend' in ws_message
    no_backend_tool.skill_manager.run_skill_script.assert_not_called()

    pip_code = '''import subprocess, sys
subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'pkg'])
'''
    assert _scan_shell_calls(pip_code, allow_package_installs=True) == []
    pip_blocked = _scan_shell_calls(pip_code, allow_package_installs=False)
    assert 'subprocess.check_call(...)' in pip_blocked

    magic_code = '''!ls
%system echo hi
%%bash'''
    magic_violations = _scan_shell_calls(magic_code)
    assert 'IPython shell escape (!...)' in magic_violations
    assert 'IPython shell magic' in magic_violations
    assert 'IPython shell cell magic' in magic_violations

    subprocess_code = '''import subprocess
subprocess.run(['ls', '-l'])
'''
    assert 'subprocess.run(...)' in _scan_shell_calls(subprocess_code)

    os_code = '''import os
os.system('echo hi')
'''
    assert 'os.system(...)' in _scan_shell_calls(os_code)
