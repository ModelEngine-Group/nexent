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
        "contracts.constants.environment": "backend/contracts/constants/environment.py",
        "contracts.knowledge_cleanse": "backend/contracts/knowledge_cleanse.py",
        "contracts.knowledge_ingestion": "backend/contracts/knowledge_ingestion.py",
        "management.services.file.cleanse_jobs": "backend/management/services/file/cleanse_jobs.py",
        "management.services.knowledge_base.ingestion_journal": "backend/management/services/knowledge_base/ingestion_journal.py",
        "management.services.knowledge_base.ingestion_coordinator": "backend/management/services/knowledge_base/ingestion_coordinator.py",
        "management.services.knowledge_base.ingestion_dispatch": "backend/management/services/knowledge_base/ingestion_dispatch.py",
        "infrastructure.rdb.knowledge_ingestion_dispatch": "infrastructure/rdb/knowledge_ingestion_dispatch.py",
        "runtime.knowledge_base.jobs": "backend/runtime/knowledge_base/jobs.py",
        "infrastructure.rdb.knowledge_file_record": "infrastructure/rdb/knowledge_file_record.py",
        "infrastructure.rdb.knowledge_ingestion": "infrastructure/rdb/knowledge_ingestion.py",
        "infrastructure.knowledge_ingestion": "infrastructure/knowledge_ingestion.py",
        "contracts.agentos": "backend/contracts/agentos.py",
        "contracts.knowledge_tool": "backend/contracts/knowledge_tool.py",
        "infrastructure.knowledge_content": "infrastructure/knowledge_content.py",
        "management.services.knowledge_base.content_authorization": "backend/management/services/knowledge_base/content_authorization.py",
        "management.services.knowledge_base.content": "backend/management/services/knowledge_base/content.py",
        "management.api.file.knowledge_content": "backend/management/api/file/knowledge_content.py",
        "runtime.knowledge_base.content": "backend/runtime/knowledge_base/content.py",
        "management.services.tool.knowledge_validation": "backend/management/services/tool/knowledge_validation.py",
        "management.services.tool.discovery": "backend/management/services/tool/discovery.py",
        "management.services.agent.preparation.knowledge_search": "backend/management/services/agent/preparation/knowledge_search.py",
        "runtime.knowledge_base.sdk_tool": "backend/runtime/knowledge_base/sdk_tool.py",
        "runtime.agentos.prepared_knowledge": "backend/runtime/agentos/prepared_knowledge.py",
        "infrastructure.rdb.model_metadata": "infrastructure/rdb/model_metadata.py",
        "contracts.agentos_knowledge": "backend/contracts/agentos_knowledge.py",
        "infrastructure.file_processing.parser": "infrastructure/file_processing/parser.py",
        "management.services.file.cleanse": "backend/management/services/file/cleanse.py",
        "management.services.knowledge_base.tool_files": "backend/management/services/knowledge_base/tool_files.py",
        "infrastructure.knowledge_cleanse": "infrastructure/knowledge_cleanse.py",
        "infrastructure.rdb.cleanse_resources": "infrastructure/rdb/cleanse_resources.py",
        "management.services.file.cleanse_lifespan": "backend/management/services/file/cleanse_lifespan.py",
        "nexent.data_process.core": "sdk/nexent/data_process/core.py",
        "runtime.knowledge_base.chunking": "backend/runtime/knowledge_base/chunking.py",
        "runtime.text_cleanse": "backend/runtime/text_cleanse.py",
        "runtime.knowledge_images": "backend/runtime/knowledge_images.py",
        "runtime.knowledge_base.image_ingestion": "backend/runtime/knowledge_base/image_ingestion.py",
        "runtime.knowledge_base.ingestion": "backend/runtime/knowledge_base/ingestion.py",
        "runtime.knowledge_base.tool_search": "backend/runtime/knowledge_base/tool_search.py",
        "runtime.knowledge_base.search": "backend/runtime/knowledge_base/search.py",
        "runtime.model.service": "backend/runtime/model/service.py",
        "infrastructure.knowledge_objects": "infrastructure/knowledge_objects.py",
        "runtime.knowledge_base.tool": "backend/runtime/knowledge_base/tool.py",
        "runtime.agentos.tools": "backend/runtime/agentos/tools.py",
        "nexent.core.tools.analyze_text_file_tool": "sdk/nexent/core/tools/analyze_text_file_tool.py",
        "management.services.tool.text_validation": "backend/management/services/tool/text_validation.py",
        "management.services.file.image_content": "backend/management/services/file/image_content.py",
        "infrastructure.file_processing.image_sources": "infrastructure/file_processing/image_sources.py",
        "nexent.multi_modal.image_codec": "sdk/nexent/multi_modal/image_codec.py",
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
