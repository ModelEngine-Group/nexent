# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prove signed file/image grants and pinned reads over this Case's owned stores."""

from io import BytesIO
from types import SimpleNamespace

from contracts.agentos_knowledge import CleanseArtifact, KnowledgeContentRequest
from contracts.errors.exceptions import RuntimeUpstreamError
from contracts.knowledge_cleanse import KnowledgeCleanseRequest
from management.services.file.cleanse import cleanse_object
from nexent.storage.models import ObjectRef, Revision
from nexent.storage.objects import read_verified_object
from PIL import Image
from runtime.knowledge_base.content import KnowledgeContentReader

from infrastructure.file_processing.objects import bind_cleanse_objects
from infrastructure.knowledge_objects import bind_knowledge_objects
from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle


def prepare_content(engine, source, policy, actor, context):
    file_id = "c" * 32
    with engine.begin() as connection:
        connection.execute(
            KnowledgeFileLifecycle.__table__.insert().values(
                file_id=file_id,
                knowledge_id=1,
                tenant_id=actor.tenant_id,
                index_name="kb-worker",
                original_filename="source.txt",
                status="UPLOADED",
                delete_flag="N",
                source_generation=0,
                source_space=source.space,
                source_key=source.key,
                source_revision=source.version,
                source_sha256=source.sha256,
            )
        )
    with BytesIO() as stream, Image.new("RGB", (200, 200), "blue") as image:
        image.save(stream, format="PNG")
        image_bytes = stream.getvalue()
    parser = SimpleNamespace(
        file_structure=lambda **kwargs: (
            [],
            [{"image_bytes": image_bytes, "image_format": "png"}],
        )
    )
    objects = bind_cleanse_objects(
        actor.tenant_id, actor.user_id, source, context=context()
    )
    try:
        artifact = cleanse_object(
            source,
            "source.txt",
            "v2",
            parser=parser,
            objects=objects,
            context=context(),
        )
    finally:
        objects.close()
    request = KnowledgeCleanseRequest(
        knowledge_id=1,
        file_id=file_id,
        file_version=0,
        source=source,
        filename="source.txt",
        idempotency_key="content-fixture",
    )
    state = policy.submit(request, context=context())
    handle = policy.claim(
        "content-parser", job_id=state.job_id, lease_seconds=30, context=context()
    )
    assert policy.begin_execution(handle, context=context())
    assert policy.transition(
        handle, status="completed", artifact=artifact, context=context()
    )
    from contracts.agentos_knowledge import KnowledgeFileGrant

    grant = KnowledgeFileGrant(
        knowledge_id=1,
        file_id=file_id,
        file_version=0,
        action="execute",
        source=source,
        artifact=artifact,
        parser_version="v2",
        filename="source.txt",
        collection="kb-worker",
        embedding_model_id=2,
    )
    inputs = bind_knowledge_objects(actor, grant, context=context())
    try:
        manifest = CleanseArtifact.model_validate_json(
            read_verified_object(
                inputs,
                ObjectRef(artifact.space, artifact.key, Revision(artifact.version)),
                sha256=artifact.sha256,
                limit=1024 * 1024,
                context=context(),
            )
        )
    finally:
        inputs.close()
    image_ref = manifest.blocks[0].object_ref
    return (
        KnowledgeContentRequest(knowledge_id=1, file_id=file_id, file_version=0),
        image_ref,
        image_bytes,
    )


async def prove_content(
    client, actor, request, image_ref, image_bytes, source_bytes, context
):
    reader = KnowledgeContentReader(client, actor)
    data, filename = await reader.read(request, context=context())
    assert data == source_bytes and filename == "source.txt"
    image_request = request.model_copy(update={"image_ref": image_ref})
    data, _ = await reader.read(image_request, context=context())
    assert data == image_bytes
    for invalid in (
        request.model_copy(update={"file_version": 1}),
        image_request.model_copy(
            update={
                "image_ref": image_ref.model_copy(update={"version": "etag:forged"})
            }
        ),
    ):
        try:
            await reader.read(invalid, context=context())
            raise AssertionError(
                "Content outside the pinned file/manifest scope was returned"
            )
        except RuntimeUpstreamError as error:
            assert error.status_code == 403
    return {"signed_content_read": True, "pinned_image_read": True}
