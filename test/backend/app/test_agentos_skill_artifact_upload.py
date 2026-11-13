# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify ordinary prepared skill output stays inside its Runtime workspace."""

import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.agents.sandbox_workspace import SandboxWorkspace
from nexent.core.tools.run_skill_script_tool import RunSkillScriptTool
from nexent.core.tools.upload_to_s3_tool import UploadToS3Tool


@pytest.mark.parametrize(("bind", "available"), [(False, True), (True, True), (False, False)])
def test_prepared_skill_uploads_workspace_files_before_cleanup(tmp_path, bind, available):
    workspace = tmp_path / "run"
    output = workspace / "outputs" / "report.txt"
    outside = tmp_path / "foreign.txt"
    protected = workspace / "inputs" / "input.txt"
    for path, data in [(output, b"report"), (outside, b"foreign"), (protected, b"input")]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    actor = NexentAgent.__new__(NexentAgent)
    actor.workspace_path = str(workspace)
    actor.workspace_mapping = SandboxWorkspace(workspace, PurePosixPath("/workspace")) if bind else None
    actor._workspace_uploads = []
    sink = Mock()
    writes = []

    def upload(path, key):
        writes.append((Path(path).read_bytes(), key))
        return available, "stored" if available else "store unavailable"

    uploader = UploadToS3Tool(
        workspace_path=str(workspace), user_id="actor", run_id="run", observer=sink,
        minio_client=SimpleNamespace(upload_file=upload, default_bucket="bucket"),
        on_upload=actor._record_workspace_upload,
    )
    uploader.workspace_mapping = actor.workspace_mapping
    actor.agent = SimpleNamespace(tools={"upload_to_s3": uploader})
    script = RunSkillScriptTool(
        observer=sink, artifact_uploader=actor._upload_skill_artifacts,
        artifact_path_resolver=actor._resolve_skill_artifact_path,
    )
    script.skill_manager = Mock()
    script.skill_manager.load_skill.return_value = {"script_outputs": {"script.py": {"kind": "file"}}}

    def declared(path, size):
        return {
            "kind": "file", "absolute_path": str(path), "file_name": path.name,
            "mime_type": "text/plain", "file_size_bytes": size,
        }

    declared_output = PurePosixPath("/workspace/outputs/report.txt") if bind else output
    script.skill_manager.run_skill_script.return_value = json.dumps({
        "status": "success",
        "artifacts": [declared(declared_output, 6), declared(outside, 7), declared(protected, 5)],
    })
    result = script.execute("skill", "script.py")

    assert writes == [(b"report", "workspace/actor/run/outputs/report.txt")]
    if not available:
        assert not uploader.uploaded_paths
        assert not sink.add_message.called
        assert json.loads(result)["artifacts"] == []
        assert "absolute_path" not in result and output.read_bytes() == b"report"
        return
    assert len(uploader.uploaded_paths) == 1
    assert not actor._workspace_uploads
    sink.add_message.assert_called_once()
    _, kind, event = sink.add_message.call_args.args
    assert kind.value == "file_artifact"
    assert event["artifacts"] == [{
        "object_name": "workspace/actor/run/outputs/report.txt", "name": "report.txt",
        "size": 6, "url": "s3://bucket/workspace/actor/run/outputs/report.txt", "mime_type": "text/plain",
    }]
    assert json.loads(result)["artifacts"] == event["artifacts"]
    assert "absolute_path" not in result and outside.read_bytes() == b"foreign"
    assert protected.read_bytes() == b"input"
