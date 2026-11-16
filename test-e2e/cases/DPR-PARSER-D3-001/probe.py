# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real Linux fork and SDK parsing; only the ObjectStore provider is controlled."""

import hashlib
import io
import json
import multiprocessing
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from time import monotonic
from types import SimpleNamespace


class ForbiddenImports:
    def find_spec(self, fullname, path=None, target=None):
        if any(
            fullname == name or fullname.startswith(name + ".")
            for name in ("data_process", "management.db", "runtime")
        ):
            raise ImportError("Forbidden source dependency: " + fullname)


sys.meta_path.insert(0, ForbiddenImports())

from contracts.agentos_knowledge import (
    CleanseArtifact,
    FileCleanseRequest,
    ObjectReference,
)
from management.services.file.cleanse_executor import CleanseExecutor
from management.services.file.process_cleanse_executor import ProcessCleanseExecutor
from nexent.storage.errors import OutcomeUnknown
from nexent.storage.models import ObjectMetadata, ObjectRef, OperationContext, Revision

from infrastructure.file_processing.isolated import run_isolated
from infrastructure.file_processing.parser import DocumentParserRuntime


class Objects:
    def __init__(self, filename, content):
        self.content = {filename: content}
        self.filename = filename

    def stat(self, ref, *, context):
        content = self.content[ref.key]
        return ObjectMetadata(
            ref,
            len(content),
            "application/octet-stream",
            sha256=hashlib.sha256(content).hexdigest(),
        )

    @contextmanager
    def open_read(self, ref, *, context):
        with io.BytesIO(self.content[ref.key]) as stream:
            yield stream

    def put(self, ref, stream, *, content_type, size, context):
        data = stream.read()
        assert len(data) == size
        digest = hashlib.sha256(data).hexdigest()
        self.content[ref.key] = data
        return ObjectMetadata(
            ObjectRef(ref.space, ref.key, Revision("sha:" + digest)),
            size,
            content_type,
            sha256=digest,
        )


def child(inherited, pipe):
    try:
        try:
            inherited.ensure_initialized()
        except RuntimeError as error:
            assert "fork" in str(error)
        else:
            raise AssertionError("inherited parser was accepted")
        assert not inherited.initialized
        runtime = DocumentParserRuntime(1, [], {})
        assert not runtime.initialized
        runtime.ensure_initialized()
        core = runtime.core
        assert runtime.initialized and runtime.core is core
        for name in (
            "OMP_NUM_THREADS",
            "MKL_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
        ):
            assert os.environ[name] == "1"
        from openpyxl import Workbook

        workbook = Workbook()
        workbook.active.append(["probe", "value"])
        workbook.active.append(["cell-fixture", 42])
        buffer = io.BytesIO()
        workbook.save(buffer)
        workbook.close()
        for filename, data, expected in (
            (
                "fixture.txt",
                b"Parser smoke fixture text.",
                "Parser smoke fixture text.",
            ),
            ("fixture.xlsx", buffer.getvalue(), "cell-fixture"),
        ):
            objects = Objects(filename, data)
            request = SimpleNamespace(
                filename=filename,
                source=ObjectReference(
                    space="cleanse",
                    key=filename,
                    version="source-v1",
                    sha256=hashlib.sha256(data).hexdigest(),
                ),
            )
            executor = CleanseExecutor(
                runtime=runtime, objects=objects, parser_version="parser-proof-v1"
            )
            ref = executor(
                {"parser_version": "parser-proof-v1"},
                request,
                context=OperationContext("parser-proof", monotonic() + 30),
            )
            assert ref.sha256 == hashlib.sha256(objects.content[ref.key]).hexdigest()
            artifact = CleanseArtifact.model_validate_json(objects.content[ref.key])
            assert artifact.source == request.source
            assert artifact.parser_version == "parser-proof-v1"
            assert expected in "\n".join(block.content for block in artifact.blocks)
            assert runtime.core is core
        assert not any(
            name == "data_process"
            or name.startswith(("data_process.", "management.db", "runtime."))
            for name in sys.modules
        )
        pipe.send(
            {
                "fork_rejected": True,
                "sdk_text_and_spreadsheet": True,
                "core_reused": True,
                "forbidden_imports_unused": True,
                "child_pid": os.getpid(),
            }
        )
    finally:
        pipe.close()


def check_isolation():
    import time

    def factory(*, context):
        def execute(payload, *, context):
            if payload == "crash":
                os._exit(17)
            time.sleep(30)

        return execute

    for payload in ("hang", "crash", "cancel"):
        stop = multiprocessing.get_context("fork").Event()

        def tick(*, context, payload=payload, stop=stop):
            if payload == "cancel":
                stop.set()

        try:
            run_isolated(
                factory,
                payload,
                context=OperationContext(
                    "failure-proof", monotonic() + 0.4, cancelled=stop
                ),
                tick=tick,
            )
        except OutcomeUnknown:
            pass
        else:
            raise AssertionError("dispatched failure was not quarantined")
        assert not multiprocessing.active_children()
    actual_parent = os.getpid()
    data = b"Isolated parser fixture text."
    request = FileCleanseRequest(
        run_id="a" * 32,
        filename="isolated.txt",
        idempotency_key="isolated",
        source=ObjectReference(
            space="cleanse",
            key="isolated.txt",
            version="source-v1",
            sha256=hashlib.sha256(data).hexdigest(),
        ),
    )

    def parser_factory():
        assert os.getpid() != actual_parent
        return CleanseExecutor(
            runtime=DocumentParserRuntime(1, [], {}),
            objects=Objects("isolated.txt", data),
            parser_version="parser-proof-v1",
        )

    ref = ProcessCleanseExecutor(parser_factory)(
        {
            "scope_kind": "run",
            "run_id": request.run_id,
            "request_payload": request.model_dump(mode="json"),
            "parser_version": "parser-proof-v1",
        },
        request,
        context=OperationContext("isolated-parser", monotonic() + 30),
    )
    assert ref.key.startswith("artifacts/" + request.source.sha256 + "/")
    assert ref.key.endswith(ref.sha256 + ".json")
    assert not multiprocessing.active_children()
    assert "nexent.data_process" not in sys.modules


if __name__ == "__main__":
    assert "nexent.data_process" not in sys.modules
    inherited = DocumentParserRuntime(1, [], {})
    assert not inherited.initialized and "nexent.data_process" not in sys.modules
    context = multiprocessing.get_context("fork")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=child, args=(inherited, writer))
    process.start()
    writer.close()
    try:
        assert reader.poll(60), "parser child timed out"
        result = reader.recv()
        process.join(5)
        assert process.exitcode == 0
        assert result["child_pid"] != os.getpid()
        assert not inherited.initialized and "nexent.data_process" not in sys.modules
        result["parent_lazy"] = True
        check_isolation()
        result["isolated_failures_reclaimed"] = True
        result["isolated_parser_rebuilt"] = True
        result["source_hashes"] = {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path("/proof/infrastructure/file_processing/parser.py"),
                Path("/proof/backend/management/services/file/cleanse_executor.py"),
                Path("/proof/sdk/nexent/data_process/core.py"),
                Path("/proof/infrastructure/file_processing/isolated.py"),
                Path(
                    "/proof/backend/management/services/file/process_cleanse_executor.py"
                ),
            )
        }
        print(json.dumps(result))
    finally:
        reader.close()
        if process.is_alive():
            process.terminate()
            process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)
        assert not process.is_alive()
        process.close()
