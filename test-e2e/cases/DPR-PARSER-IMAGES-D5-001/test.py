# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Probe actual offline service images without mounting product or application data."""

import hashlib
import json
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.mark.stage("D5")
@pytest.mark.case_id("DPR-PARSER-IMAGES-D5-001")
def test_role_parser_images(record_property):
    root = Path(__file__).resolve().parents[3]
    script = Path(__file__).with_name("probe.py").read_text(encoding="utf-8")
    run_id = uuid4().hex
    evidence = {}
    containers = []
    sources = {
        "infrastructure.file_processing.parser": "infrastructure/file_processing/parser.py",
        "management.services.file.cleanse": "backend/management/services/file/cleanse.py",
        "management.services.file.cleanse_lifespan": "backend/management/services/file/cleanse_lifespan.py",
        "nexent.data_process.core": "sdk/nexent/data_process/core.py",
        "runtime.knowledge_base.chunking": "backend/runtime/knowledge_base/chunking.py",
        "nexent.multi_modal.image_filter": "sdk/nexent/multi_modal/image_filter.py",
    }
    try:
        for role in ("management", "runtime"):
            tag = f"nexent/nexent-{role}:latest"
            image = subprocess.check_output(
                ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
                text=True,
                timeout=15,
            ).strip()
            name = "nexent-parser-image-" + role + "-" + run_id
            containers.append(name)
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "-i",
                    "--name",
                    name,
                    "--label",
                    "nexent.test_run=" + run_id,
                    "--network",
                    "none",
                    "-e",
                    "HF_HUB_OFFLINE=1",
                    "--entrypoint",
                    "/opt/backend/.venv/bin/python",
                    image,
                    "-",
                    role,
                ],
                input=script,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            record = json.loads(result.stdout.splitlines()[-1])
            assert (
                record["role"] == role
                and record["peer_absent"]
                and record["cpu"]
                and record["nltk_safe"]
            )
            for module, actual_hash in record["source_hashes"].items():
                assert (
                    actual_hash
                    == hashlib.sha256((root / sources[module]).read_bytes()).hexdigest()
                ), module
            if role == "management":
                assert record["models_loaded"] == 2 and record["parsed_files"] == [
                    "input.txt",
                    "input.json",
                    "input.xlsx",
                ]
                assert record["extraction_only"]
                assert record["backbone_tensors_equal"] > 0
                assert record["migrations"] == {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (root / "deploy/sql/migrations").glob("*.sql")
                }
            else:
                assert (
                    record["clip_loaded"]
                    and record["clip_inference"]
                    and record["extraction_absent"]
                )
                assert record["chunks"] > 1
                assert record["json_chunks"] >= 1
            evidence[role] = {"image_id": image, **record}
    finally:
        for name in reversed(containers):
            subprocess.run(
                ["docker", "rm", "-f", "-v", name],
                capture_output=True,
                timeout=15,
                check=True,
            )
    remaining = subprocess.check_output(
        ["docker", "ps", "-aq", "--filter", "label=nexent.test_run=" + run_id],
        text=True,
        timeout=15,
    )
    assert not remaining.strip()
    record_property("parser_service_images", json.dumps(evidence, sort_keys=True))
