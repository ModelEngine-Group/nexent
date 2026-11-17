# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read this script from stdin, using only built image code and offline weights."""

import hashlib
import importlib
import importlib.metadata
import importlib.util
import io
import json
import logging
import math
import os
import shutil
import sys
from pathlib import Path

import torch

role = sys.argv[1]
assert role in {"management", "runtime"}
peer = "runtime" if role == "management" else "management"
assert not Path("/opt/backend", peer).exists()
assert importlib.util.find_spec("flower") is None
assert torch.version.cuda is None
assert os.environ["HF_HUB_OFFLINE"] == "1"
nltk = Path(os.environ["NLTK_DATA"])
assert nltk.stat().st_uid == 0 and not nltk.stat().st_mode & 0o022
for entry in nltk.rglob("*"):
    assert entry.stat().st_uid == 0 and not entry.stat().st_mode & 0o022
torch.set_num_threads(1)
evidence = {"role": role, "peer_absent": True, "cpu": True, "nltk_safe": True}
for package in ("nexent", "torch", "transformers", "unstructured", "numpy", "pydantic"):
    matches = list(importlib.metadata.distributions(name=package))
    assert len(matches) == 1, package

if role == "management":
    assert os.environ["MANAGEMENT_FILE_CLEANSE_ENABLED"] == "true"
    assert not Path("/opt/models/clip-vit-base-patch32").exists()
    assert importlib.util.find_spec("unstructured_inference") is not None
    for command in ("soffice", "pandoc", "pdftoppm", "tesseract"):
        assert shutil.which(command), command
    from openpyxl import Workbook

    from infrastructure.file_processing.parser import DocumentParserRuntime

    parser = DocumentParserRuntime(
        1,
        ["unstructured_default", "table_transformer"],
        {
            "unstructured_default": os.environ[
                "UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH"
            ],
            "table_transformer": os.environ["TABLE_TRANSFORMER_MODEL_PATH"],
        },
    )
    parser.ensure_initialized()
    models = parser.core.model_registry._models
    assert set(models) == {"unstructured_default", "table_transformer"}
    assert all(getattr(model, "model", None) is not None for model in models.values())
    table_path = Path(os.environ["TABLE_TRANSFORMER_MODEL_PATH"])
    assert (
        json.loads((table_path / "config.json").read_text())["use_pretrained_backbone"]
        is False
    )
    backbone = {
        name: tensor
        for name, tensor in models["table_transformer"].model.state_dict().items()
        if name.startswith("model.backbone.")
    }
    assert backbone
    if (table_path / "model.safetensors").exists():
        from safetensors import safe_open

        with safe_open(
            table_path / "model.safetensors", framework="pt", device="cpu"
        ) as checkpoint:
            keys = set(checkpoint.keys())
            for name, tensor in backbone.items():
                assert name in keys and torch.equal(
                    tensor.cpu(), checkpoint.get_tensor(name)
                ), name
    else:
        checkpoint = torch.load(
            table_path / "pytorch_model.bin", map_location="cpu", weights_only=True
        )
        for name, tensor in backbone.items():
            assert name in checkpoint and torch.equal(tensor.cpu(), checkpoint[name]), (
                name
            )
    evidence["backbone_tensors_equal"] = len(backbone)
    files = [
        ("input.txt", b"Parser image sentinel document."),
        ("input.json", b'{"sentinel":"structural data"}'),
    ]
    workbook = Workbook()
    workbook.active.append(["kind", "value"])
    workbook.active.append(["sentinel", "spreadsheet content"])
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    files.append(("input.xlsx", stream.getvalue()))
    stream.close()
    for filename, data in files:
        blocks, _ = parser.file_structure(file_data=data, filename=filename)
        if filename.endswith(".json"):
            assert len(blocks) == 1 and blocks[0]["content"] == ""
            assert blocks[0]["metadata"] == {"element_type": "JSONSource", "source_format": "json"}
        else:
            assert blocks and any("sentinel" in block["content"].lower() for block in blocks), filename
    evidence.update(
        models_loaded=2, parsed_files=[name for name, _ in files], extraction_only=True
    )
    evidence["migrations"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in Path("/opt/deploy/sql/migrations").glob("*.sql")
    }
    modules = [
        "infrastructure.file_processing.parser",
        "management.services.file.cleanse",
        "management.services.knowledge_base.tool_files",
        "infrastructure.knowledge_cleanse",
        "infrastructure.rdb.cleanse_resources",
        "management.services.file.cleanse_lifespan",
        "nexent.data_process.core",
    ]
else:
    assert not Path("/opt/models/yolox").exists()
    assert not Path("/opt/models/table-transformer-structure-recognition").exists()
    assert importlib.util.find_spec("unstructured_inference") is None
    from contracts.agentos_knowledge import (
        CleanseArtifact,
        CleanseBlock,
        ObjectReference,
    )
    from nexent.multi_modal.image_filter import ImageImportanceFilter
    from PIL import Image
    from runtime.knowledge_base.chunking import chunk_text

    content = "Runtime chunk sentinel. " * 20
    artifact = CleanseArtifact(
        source=ObjectReference(
            space="files",
            key="fixture.txt",
            version="etag:fixture",
            sha256=hashlib.sha256(b"fixture").hexdigest(),
        ),
        parser_version="v1",
        blocks=[
            CleanseBlock(
                ordinal=0,
                kind="text",
                content=content,
                sha256=hashlib.sha256(content.encode()).hexdigest(),
                location={"element_type": "NarrativeText"},
            )
        ],
    )
    chunks = chunk_text(
        artifact,
        filename="fixture.txt",
        strategy="basic",
        max_characters=100,
        new_after_n_chars=80,
    )
    assert chunks and "sentinel" in " ".join(chunk["content"] for chunk in chunks)
    json_source = b'{"sentinel":"structural data"}'
    json_artifact = CleanseArtifact(source=ObjectReference(space="files", key="fixture.json",
        version="etag:fixture", sha256=hashlib.sha256(json_source).hexdigest()), parser_version="v1",
        blocks=[CleanseBlock(ordinal=0, kind="text", content="", sha256=hashlib.sha256(b"").hexdigest(),
            location={"element_type": "JSONSource", "source_format": "json"})])
    json_chunks = chunk_text(json_artifact, filename="fixture.json", strategy="basic",
        max_characters=100, new_after_n_chars=80, json_source=json_source)
    assert json_chunks and "sentinel" in " ".join(chunk["content"] for chunk in json_chunks)
    log = io.StringIO()
    handler = logging.StreamHandler(log)
    logger = logging.getLogger("nexent.multi_modal.image_filter")
    logger.addHandler(handler)
    scorer = ImageImportanceFilter(os.environ["CLIP_MODEL_PATH"])
    image = Image.new("RGB", (256, 256), "blue")
    try:
        result = scorer.filter(image, enabled=True)
        assert (
            scorer.clip_available
            and scorer.model is not None
            and scorer.processor is not None
        )
        assert (
            "clip_inference_failed" not in log.getvalue()
            and "clip_load_failed" not in log.getvalue()
        )
        probabilities = result["probabilities"]
        assert all(
            math.isfinite(value) and 0 <= value <= 1 for value in probabilities.values()
        )
        assert abs(sum(probabilities.values()) - 1) < 1e-5
    finally:
        image.close()
        logger.removeHandler(handler)
        handler.close()
        log.close()
    evidence.update(
        clip_loaded=True,
        clip_inference=True,
        chunks=len(chunks), json_chunks=len(json_chunks),
        extraction_absent=True,
    )
    modules = ["runtime.knowledge_base.chunking", "nexent.multi_modal.image_filter",
               "runtime.knowledge_base.image_ingestion", "runtime.knowledge_base.ingestion",
               "runtime.knowledge_base.tool_search", "runtime.knowledge_base.search",
               "runtime.model.service", "infrastructure.knowledge_objects",
               "runtime.text_cleanse", "runtime.knowledge_images", "runtime.agentos.tools",
               "nexent.core.tools.analyze_text_file_tool", "runtime.knowledge_base.tool",
               "runtime.knowledge_base.sdk_tool", "runtime.agentos.prepared_knowledge",
               "infrastructure.rdb.model_metadata", "runtime.knowledge_base.content", "runtime.knowledge_base.jobs"]

if role == "management":
    modules.extend(["management.services.tool.text_validation", "management.services.file.image_content",
                    "infrastructure.file_processing.image_sources", "management.services.tool.knowledge_validation",
                    "management.services.tool.discovery", "management.services.agent.preparation.knowledge_search",
                    "management.services.knowledge_base.content_authorization", "management.services.knowledge_base.content",
                    "management.api.file.knowledge_content", "management.services.file.cleanse_jobs",
                    "management.services.knowledge_base.ingestion_journal", "management.services.knowledge_base.ingestion_coordinator", "infrastructure.rdb.knowledge_ingestion",
                    "infrastructure.knowledge_ingestion", "management.services.knowledge_base.ingestion_dispatch",
                    "infrastructure.rdb.knowledge_ingestion_dispatch", "management.services.knowledge_base.ingestion",
                    "management.services.knowledge_base.ingestion_selection", "management.services.knowledge_base.file_selection",
                    "management.services.file.local_knowledge_source", "infrastructure.file_processing.local_source",
                    "management.services.file.local_source_staging", "infrastructure.local_source_staging",
                    "infrastructure.rdb.local_source_staging"])

modules.extend(["nexent.multi_modal.image_codec", "contracts.agentos", "contracts.agentos_knowledge", "contracts.knowledge_tool",
                "infrastructure.knowledge_content", "contracts.knowledge_cleanse", "contracts.knowledge_ingestion",
                "infrastructure.rdb.knowledge_file_record", "contracts.constants.environment"])

evidence["source_hashes"] = {
    name: hashlib.sha256(
        Path(importlib.import_module(name).__file__).read_bytes()
    ).hexdigest()
    for name in modules
}
if role == "management":
    assert not any(name == "runtime" or name.startswith("runtime.") for name in sys.modules)
assert importlib.util.find_spec("nexent.core.tools.knowledge_base_search_tool") is None
print(json.dumps(evidence, sort_keys=True))
