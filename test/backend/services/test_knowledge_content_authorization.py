# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Content grants require current resource permission and manifest membership."""

from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import (
    CleanseArtifact,
    CleanseBlock,
    KnowledgeContentRequest,
    ObjectReference,
)
from management.services.knowledge_base.content_authorization import (
    KnowledgeContentAuthorization,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import FieldPatch, PageRequest, RecordQuery, Revision

from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_authorization import (
    setup as setup,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_cleanse_jobs import knowledge_request


@pytest.fixture
def content(setup):
    _policy, payload, update, resource_policy, jobs = setup
    source = knowledge_request().source
    image = ObjectReference(
        space="files",
        key=f"images/{source.sha256}/{'c' * 64}.png",
        version="image-v1",
        sha256="c" * 64,
    )
    artifact = CleanseArtifact(
        source=source,
        parser_version="v2",
        blocks=[
            CleanseBlock(ordinal=0, kind="image", sha256=image.sha256, object_ref=image)
        ],
    )
    load = Mock(return_value=artifact)
    content_policy = KnowledgeContentAuthorization(
        jobs, resource_policy.records, load, user_id="user-a"
    )
    request = KnowledgeContentRequest(
        knowledge_id=1, file_id=payload.file_id, file_version=0
    )
    return content_policy, request, image, load, update


def test_source_read_is_exact_and_does_not_require_a_cleanse_artifact(content):
    policy, request, _, load, _ = content
    grant = policy.authorize(request, context=context())
    assert (
        grant.object_ref == knowledge_request().source
        and grant.filename == "source.txt"
    )
    assert grant.model_dump(
        include={"knowledge_id", "file_id", "file_version"}
    ) == request.model_dump(exclude={"image_ref"})
    load.assert_not_called()


def test_read_only_member_can_read_manifest_image(content):
    policy, request, image, load, update = content
    update("cleanse_knowledge", created_by="other", ingroup_permission="READ_ONLY")
    row, = policy.jobs.query("file_cleanse_jobs", RecordQuery(), PageRequest(limit=1), context=context()).items
    assert policy.jobs.patch("file_cleanse_jobs", row["id"], FieldPatch(set_values={"user_id": "another-cleaner"}),
                             expected=Revision(str(row["revision"])), context=context()).matched
    grant = policy.authorize(
        request.model_copy(update={"image_ref": image}), context=context()
    )
    assert grant.object_ref == image and grant.image_ref == image
    assert load.call_count == 1


@pytest.mark.parametrize(
    "dataset,values",
    [
        ("cleanse_files", {"source_generation": 1}),
        ("cleanse_files", {"status": "DELETE_REQUESTED"}),
        ("cleanse_files", {"delete_flag": "Y"}),
        ("cleanse_memberships", {"tenant_id": "other"}),
        ("cleanse_knowledge", {"created_by": "other", "ingroup_permission": "NONE"}),
    ],
)
def test_stale_or_unauthorized_content_is_rejected_before_object_io(
    content, dataset, values
):
    policy, request, image, load, update = content
    update(dataset, **values)
    with pytest.raises(ScopeDenied):
        policy.authorize(
            request.model_copy(update={"image_ref": image}), context=context()
        )
    load.assert_not_called()


@pytest.mark.parametrize(
    "changes", [{"key": "images/other.png"}, {"version": "other"}, {"sha256": "d" * 64}]
)
def test_image_must_match_manifest_key_version_and_hash(content, changes):
    policy, request, image, _, _ = content
    with pytest.raises(ScopeDenied):
        policy.authorize(
            request.model_copy(update={"image_ref": image.model_copy(update=changes)}),
            context=context(),
        )


def test_changed_source_rejects_old_manifest(content):
    policy, request, image, load, update = content
    update("cleanse_files", source_revision="replaced")
    with pytest.raises(ScopeDenied):
        policy.authorize(
            request.model_copy(update={"image_ref": image}), context=context()
        )
    load.assert_not_called()


def test_manifest_identity_is_checked_after_loading(content):
    policy, request, image, load, _ = content
    load.return_value = load.return_value.model_copy(update={"parser_version": "other"})
    with pytest.raises(ScopeDenied):
        policy.authorize(
            request.model_copy(update={"image_ref": image}), context=context()
        )


@pytest.mark.parametrize('foreign', [None, 'file', 'version', 'job'])
def test_private_manifest_directory_controls_image_authority(content, foreign):
    policy, request, image, load, _ = content
    row, = policy.jobs.query('file_cleanse_jobs', RecordQuery(), PageRequest(limit=1), context=context()).items
    start = f'knowledge-cleanse/{request.knowledge_id}/{request.file_id}/{request.file_version}/{row["job_id"]}/'
    reference = ObjectReference.model_validate(row['artifact'])
    reference = reference.model_copy(update={'key': start + 'artifacts/' + knowledge_request().source.sha256 + '/' + reference.sha256 + '.json'})
    policy.jobs.patch('file_cleanse_jobs', row['id'], FieldPatch(set_values={'artifact': reference.model_dump(mode='json')}),
                      expected=Revision(str(row['revision'])), context=context())
    selected = image.model_copy(update={'key': start + image.key})
    load.return_value = load.return_value.model_copy(update={'blocks': [
        CleanseBlock(ordinal=0, kind='image', sha256=selected.sha256, object_ref=selected),
    ]})
    if foreign:
        parts = selected.key.split('/')
        position = {'file': 2, 'version': 3, 'job': 4}[foreign]
        parts[position] = 'd' * 32 if foreign != 'version' else '1'
        selected = selected.model_copy(update={'key': '/'.join(parts)})
        with pytest.raises(ScopeDenied):
            policy.authorize(request.model_copy(update={'image_ref': selected}), context=context())
        load.assert_not_called()
    else:
        assert policy.authorize(request.model_copy(update={'image_ref': selected}), context=context()).object_ref == selected
        load.assert_called_once()
