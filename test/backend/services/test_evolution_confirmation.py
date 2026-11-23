# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import json
from hashlib import sha256

import pytest
from pydantic import ValidationError

from contracts.confirmation import ConfirmationManifest
from contracts.evolution_sources import example_source_keys, task_digest
from management.cli.confirmation_manifest import compile_private_suite


def _case(**changes):
    return {"agent_id":1,"version_no":2,"query":"Private input","expected":"Private answer",
            "family":"Meeting","source_group":"Private source", **changes}


def compile_at(path, *cases):
    path.write_text(json.dumps(list(cases)), encoding="utf-8")
    return compile_private_suite(path)


def test_private_suite_serializes_only_digests_and_binds_input_answer_and_attachment(tmp_path):
    pack = tmp_path / "tasks.json"
    file = tmp_path / "local.txt"
    file.write_bytes(b"Private evidence")
    task = _case(attachments=[{"name":"agenda.txt","object_name":file.name}], followups=[{"query":"Private follow-up"}])
    first = compile_at(pack, task)
    encoded = json.dumps(first.canonical())
    assert "Private" not in encoded and "agenda.txt" not in encoded and "local.txt" not in encoded
    assert set(first.cases[0].sources) == example_source_keys({"query":task["query"], "source_group":task["source_group"],
        "attachments":[{"sha256":sha256(file.read_bytes()).hexdigest()}]})
    revised = compile_at(pack, {**task,"expected":"changed"})
    assert revised.cases[0].digest != first.cases[0].digest and revised.cases[0].sources == first.cases[0].sources
    file.write_bytes(b"changed material")
    assert compile_at(pack, task).cases[0].digest != first.cases[0].digest
    other = _case(query="Another question", source_group="Independent document")
    assert task_digest(compile_at(pack, task, other).canonical()) == task_digest(compile_at(pack, other, task).canonical())


def test_compiler_rejects_mixed_scope_duplicate_tasks_and_paths_outside_the_suite(tmp_path):
    pack = tmp_path / "tasks.json"
    with pytest.raises(ValueError):
        compile_at(pack, _case(), _case(version_no=1))
    with pytest.raises(ValueError):
        compile_at(pack, _case(), _case())
    with pytest.raises(ValueError):
        compile_at(pack, _case(attachments=[{"name":"input.txt","object_name":"../input.txt"}]))
    with pytest.raises(ValidationError):
        compile_at(pack, _case(source_group="   "))
    public = compile_at(pack, _case()).canonical()
    public["cases"][0]["expected"] = "private"
    with pytest.raises(ValidationError):
        ConfirmationManifest.model_validate(public)
