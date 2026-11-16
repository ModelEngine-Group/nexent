# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compare real format processing with structural extraction plus Runtime chunking."""

import base64
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path


def runtime_only():
    class ForbiddenImports:
        def find_spec(self, fullname, path=None, target=None):
            if any(
                fullname == name or fullname.startswith(name + ".")
                for name in (
                    "management",
                    "data_process",
                    "unstructured_inference",
                    "torch",
                    "transformers",
                    "unstructured.partition.auto",
                    "unstructured.partition.docx",
                    "unstructured.partition.pdf",
                    "unstructured.partition.text",
                    "unstructured.partition.xlsx",
                    "unstructured.partition.common",
                )
            ):
                raise ImportError("Forbidden Runtime chunk dependency: " + fullname)

    sys.meta_path.insert(0, ForbiddenImports())
    from contracts.agentos_knowledge import CleanseArtifact
    from runtime.knowledge_base.chunking import chunk_text

    cases = json.load(sys.stdin)
    for case in cases:
        value = CleanseArtifact.model_validate(case["artifact"])
        result = chunk_text(
            value,
            filename=case["filename"],
            strategy=case["strategy"],
            max_characters=128,
            new_after_n_chars=80,
            json_source=base64.b64decode(case["json_source"])
            if case["json_source"]
            else None,
        )
        if result != case["expected"]:
            raise AssertionError(
                json.dumps(
                    {
                        "filename": case["filename"],
                        "strategy": case["strategy"],
                        "actual": result,
                        "expected": case["expected"],
                    }
                )
            )
    print(
        json.dumps(
            {"equivalent_cases": len(cases), "no_parser_or_management_import": True}
        )
    )


def reference():
    from contracts.agentos_knowledge import ObjectReference
    from docx import Document
    from management.services.file.cleanse import prepare_artifact
    from nexent.data_process import DataProcessCore
    from openpyxl import Workbook

    doc = Document()
    doc.add_heading("First title", level=1)
    doc.add_paragraph(
        "The first section has enough words to form a real paragraph. " * 4
    )
    doc.add_heading("Second title", level=1)
    doc.add_paragraph("The second section contains a different paragraph. " * 4)
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Name", "Value"
    table.cell(1, 0).text, table.cell(1, 1).text = "sample", "42"
    doc_bytes = io.BytesIO()
    doc.save(doc_bytes)
    book = Workbook()
    book.active.append(["heading", "value"])
    book.active.append(["cell fixture", 42])
    book.create_sheet("Second").append(["another cell"])
    book_bytes = io.BytesIO()
    book.save(book_bytes)
    book.close()
    files = (
        (
            "source.txt",
            b"First heading\n\nA real paragraph has multiple words and a final period.\n\nSecond heading\n\nAnother real paragraph follows.",
        ),
        ("source.docx", doc_bytes.getvalue()),
        (
            "source.json",
            b'{"first":"a long value with words repeated to check boundaries", "second": [1,2,3], "third": {"nested":42}}',
        ),
        ("invalid.json", b"{not valid JSON: retain the existing plain text behavior}"),
        ("source.xlsx", book_bytes.getvalue()),
        (
            "source.md",
            b"# First title\n\nA markdown paragraph contains enough words for this check.\n\n# Second title\n\nAnother markdown paragraph ends here.",
        ),
        (
            "source.html",
            b"<html><body><h1>First title</h1><p>A long HTML paragraph has multiple words to test chunk grouping.</p><h1>Second title</h1><p>Another HTML paragraph follows.</p></body></html>",
        ),
        ("source.csv", b"Name,Value\nsample,42\nother,100\n"),
    )
    core = DataProcessCore()
    cases = []
    for filename, data in files:
        source = ObjectReference(
            space="files",
            key=filename,
            version="fixture-v1",
            sha256=hashlib.sha256(data).hexdigest(),
        )
        artifact = prepare_artifact(data, filename, source, "structure-v2", parser=core)
        assert artifact.source == source
        assert artifact.blocks
        if filename.endswith(".docx"):
            assert any(
                block.location.get("element_type") == "Title"
                for block in artifact.blocks
            )
            assert any(block.kind == "table" for block in artifact.blocks)
        for strategy in ("basic", "by_title", "none"):
            expected, images = core.file_process(
                data, filename, strategy, max_characters=128, new_after_n_chars=80
            )
            assert images == []
            cases.append(
                {
                    "filename": filename,
                    "strategy": strategy,
                    "expected": expected,
                    "artifact": artifact.model_dump(mode="json"),
                    "json_source": base64.b64encode(data).decode()
                    if filename.endswith(".json")
                    else None,
                }
            )
    result = subprocess.run(
        [sys.executable, __file__, "--runtime"],
        input=json.dumps(cases),
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    proof = json.loads(result.stdout.splitlines()[-1])
    assert (
        proof["equivalent_cases"] == 24
        and proof["no_parser_or_management_import"] is True
    )
    proof["formats"] = [name for name, _ in files]
    proof["source_hashes"] = {
        path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for path in (
            "/proof/backend/runtime/knowledge_base/chunking.py",
            "/proof/backend/management/services/file/cleanse.py",
            "/proof/sdk/nexent/data_process/core.py",
            "/proof/sdk/nexent/data_process/unstructured_processor.py",
        )
    }
    print(json.dumps(proof))


if __name__ == "__main__":
    runtime_only() if "--runtime" in sys.argv else reference()
