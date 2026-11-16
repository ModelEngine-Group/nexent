# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual scoped worker and object publication for identical run source bytes."""

import hashlib
from io import BytesIO

from contracts.agentos_knowledge import (
    CleanseArtifact,
    FileCleanseLookup,
    FileCleanseRequest,
    ObjectReference,
)
from management.services.file.cleanse_execution import consume_cleanse_once
from management.services.file.cleanse_executor import CleanseExecutor
from management.services.file.cleanse_worker import HANDLER
from management.services.file.run_cleanse_service import FileCleanseService
from nexent.storage.errors import NotFound, ScopeDenied
from nexent.storage.models import ObjectRef, Revision, StorageScope, TaskEnvelope

from infrastructure.file_processing.objects import bind_cleanse_objects
from infrastructure.object_storage.composition import (
    _configured_client,
    _configured_environment,
    bind_source_objects,
)
from infrastructure.object_storage.port import ObjectBinding, S3ObjectStore


class Parser:
    def ensure_initialized(self):
        pass

    def file_structure(self, *, file_data, filename):
        return (
            [{"content": file_data.decode("utf-8")}],
            [{"image_bytes": b"controlled-image", "image_format": "png"}],
        )


def check_run_outputs(queue, context, kb_artifact):
    environment = _configured_environment()
    content = b"identical run source"
    inputs = bind_source_objects(
        "tenant-a",
        "user-a",
        "attachments/user-a/run-source.txt",
        environment.MINIO_DEFAULT_BUCKET,
    )
    reader = S3ObjectStore(
        StorageScope("management", "tenant-a", "user-a", {"files"}),
        ObjectBinding("files", environment.MINIO_DEFAULT_BUCKET, "", {"management"}),
        _configured_client,
    )
    try:
        original = inputs.put(
            ObjectRef("files", "attachments/user-a/run-source.txt"),
            BytesIO(content),
            content_type="text/plain",
            size=len(content),
            context=context(),
        )
        source = ObjectReference(
            space="files",
            key=original.ref.key,
            version=original.ref.version.value,
            sha256=original.sha256,
        )
        api = FileCleanseService(parser_version="parser-v1")
        calls, manifests, image_keys, lookups = [], [], [], []

        def execute(row, request, *, tick, context):
            tick(context=context)
            lookup = FileCleanseLookup(run_id=row["run_id"], job_id=row["job_id"])
            objects = bind_cleanse_objects(
                "tenant-a", "user-a", request.source, context=context, run=lookup
            )
            executor = CleanseExecutor(
                runtime=Parser(), objects=objects, parser_version="parser-v1"
            )
            try:
                # A run writer cannot fall back to the former shared output namespace.
                for prefix in (
                    "",
                    f"run-cleanse/{'f' * 32}/{lookup.job_id}/",
                    f"run-cleanse/{lookup.run_id}/{'f' * 32}/",
                ):
                    try:
                        objects.put(
                            ObjectRef(
                                "files",
                                f"{prefix}images/{source.sha256}/{'0' * 64}.png",
                            ),
                            BytesIO(b"x"),
                            content_type="image/png",
                            size=1,
                            context=context,
                        )
                    except ScopeDenied:
                        pass
                    else:
                        raise AssertionError("foreign output capability accepted")
                result = executor(row, request, context=context)
                tick(context=context)
                calls.append(lookup.job_id)
                return result
            finally:
                executor.close()

        for run_id, key in (
            ("1" * 32, "first"),
            ("1" * 32, "second"),
            ("debug-" + "2" * 32, "first"),
        ):
            request = FileCleanseRequest(
                run_id=run_id,
                source=source,
                filename="run-source.txt",
                idempotency_key=key,
            )
            state = api.submit(
                request, tenant_id="tenant-a", user_id="user-a", context=context()
            )
            queue.enqueue(
                TaskEnvelope(state.job_id, HANDLER, {"job_id": state.job_id}),
                context=context(),
            )
            assert consume_cleanse_once(
                queue,
                owner_id="run-output-proof",
                parser_version="parser-v1",
                execute=execute,
                context=context(),
            )
            lookup = FileCleanseLookup(run_id=run_id, job_id=state.job_id)
            completed = api.inspect(
                lookup, tenant_id="tenant-a", user_id="user-a", context=context()
            )
            assert completed.status == "completed"
            ref = completed.artifact
            prefix = f"run-cleanse/{run_id}/{state.job_id}/"
            assert ref.key.startswith(prefix + "artifacts/")
            with reader.open_read(
                ObjectRef("files", ref.key, Revision(ref.version)), context=context()
            ) as stream:
                data = stream.read()
            assert hashlib.sha256(data).hexdigest() == ref.sha256
            artifact = CleanseArtifact.model_validate_json(data)
            assert artifact.source == source and artifact.parser_version == "parser-v1"
            assert artifact.blocks[0].content == content.decode("utf-8")
            image = artifact.blocks[1].object_ref
            assert image.key.startswith(prefix + "images/")
            with reader.open_read(
                ObjectRef("files", image.key, Revision(image.version)),
                context=context(),
            ) as stream:
                image_data = stream.read()
            assert image_data == b"controlled-image"
            assert hashlib.sha256(image_data).hexdigest() == image.sha256
            manifests.append(ref.key)
            image_keys.append(image.key)
            lookups.append(lookup)
        assert len(set(calls)) == len(set(manifests)) == len(set(image_keys)) == 3
        for lookup in lookups:
            assert api.release(lookup, tenant_id="tenant-a", user_id="user-a", context=context()).released
            assert api.release(lookup, tenant_id="tenant-a", user_id="user-a", context=context()).released
            assert api.inspect(lookup, tenant_id="tenant-a", user_id="user-a", context=context()).status == "released"
        for key in manifests + image_keys:
            try:
                reader.stat(ObjectRef("files", key), context=context())
            except NotFound:
                pass
            else:
                raise AssertionError("released run output remains readable")
        with inputs.open_read(original.ref, context=context()) as stream:
            assert stream.read() == content
        with reader.open_read(ObjectRef(kb_artifact.space, kb_artifact.key,
            Revision(kb_artifact.version)), context=context()) as stream:
            assert hashlib.sha256(stream.read()).hexdigest() == kb_artifact.sha256
    finally:
        reader.close()
        inputs.close()
