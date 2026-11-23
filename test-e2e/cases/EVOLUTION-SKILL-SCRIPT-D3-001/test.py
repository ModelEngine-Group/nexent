# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import docker
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "sdk"), str(ROOT)]


@pytest.mark.case_id("EVOLUTION-SKILL-SCRIPT-D3-001")
@pytest.mark.stage("D3")
def test_script_process(tmp_path):
    from contracts.agentos import ReplayToolObservation
    from management.services.evaluation.tool_use import judge_tool_use
    from management.services.evaluation.skill_script_repairs import replace_function
    from nexent.core.agents.resources.replay_tools import ReplayToolRecorder
    from nexent.core.agents.sandbox.execution import SandboxSkillScriptRunner
    from nexent.core.tools.run_skill_script_tool import RunSkillScriptTool, SkillScriptExecutionError

    client = docker.from_env()
    image = client.images.get(os.environ.get("NEXENT_TEST_SANDBOX_IMAGE", "nexent/nexent-sandbox:latest"))
    container = client.containers.run(image.id, entrypoint="sleep", command=["120"], detach=True,
                                      network_disabled=True, labels={"nexent.test.case": "skill-process"})
    try:
        executor = SimpleNamespace(container=container, _nexent_backend="docker")
        arguments = {"skill_name": "weekly", "script_path": "scripts/report.py", "params": "business-value"}
        expectation = {"rules": [{"name": "run_skill_script", "arguments": arguments,
                                  "min_calls": 1, "max_calls": 1, "expected_script_stdout": "BUSINESS-VALUE\n"}]}
        baseline = "import sys\ndef report(value):\n    return value\nprint(report(sys.argv[1]))\n"
        candidate = replace_function(baseline, "report", "def report(value):\n    return value.upper()")
        scripts = [baseline, candidate,
                   'import sys\nsys.exit(3)', 'print("unused")']
        for index, source in enumerate(scripts):
            root = tmp_path / str(index)
            skill = root / "org" / "weekly"
            (skill / "scripts").mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: weekly\ndescription: weekly summary\n---\nRun the script.", encoding="utf8")
            script = skill / arguments["script_path"]
            script.write_bytes(source.encode())
            workspace = f"/home/sandbox/task-{index}"
            runner = SandboxSkillScriptRunner(executor, 10, workspace_path=workspace)
            tool = RunSkillScriptTool(local_skills_dir=str(root), tenant_id="org", workspace_path=workspace,
                                      authorized_skill_names=["weekly"], isolated_skills_root=True, execution_backend=runner)
            recorder = ReplayToolRecorder(None, {tool.name: list(arguments)}, watch_skill_process=index != 3)
            recorder.bind(tool, tool.name)
            if index == 2:
                with pytest.raises(SkillScriptExecutionError):
                    tool.forward(**arguments)
            else:
                tool.forward(**arguments)
            observation = ReplayToolObservation.model_validate(recorder.receipt())
            grade = judge_tool_use(expectation, observation)
            assert grade["status"] == ["fail", "pass", "fail", "missing_evidence"][index], grade
            assert "business-value" not in json.dumps(recorder.receipt()).lower()
            if index < 3:
                process, = grade["script_evidence"]
                assert process["script"] == hashlib.sha256(script.read_bytes()).hexdigest()
                assert process["image"] == image.id and process["input_matches"]
                assert process["exit_code"] == (3 if index == 2 else 0)
            else:
                assert grade["reason"] == "unverified_skill_process"
    finally:
        try:
            container.remove(force=True)
        finally:
            client.close()
