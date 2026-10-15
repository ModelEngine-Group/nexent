"""Shared Agent values retain their existing fields and frozen behavior."""

from dataclasses import FrozenInstanceError, asdict

import pytest

from contracts.agent import (
    AgentModelProjection,
    AgentRunContext,
    SystemAgentRef,
    WorkbenchReleaseManifest,
    WORKBENCH_OFFICIAL_SKILL_NAMES,
)


def test_system_reference_preserves_identity_and_frozen_fields():
    ref = SystemAgentRef("tenant", "workbench_main", 17, 2)
    assert asdict(ref) == {
        "tenant_id": "tenant", "system_key": "workbench_main",
        "agent_id": 17, "version_no": 2,
    }
    with pytest.raises(FrozenInstanceError):
        ref.version_no = 3


def test_release_manifest_preserves_default_and_explicit_skill_sets():
    manifest = WorkbenchReleaseManifest("1.0", ("knowledge_base_search",))
    assert manifest.official_skill_names == WORKBENCH_OFFICIAL_SKILL_NAMES
    assert WorkbenchReleaseManifest("1.0", (), ("custom",)).official_skill_names == ("custom",)


def test_projection_preserves_mutable_field_container_and_deleted_ids():
    fields = {"model_ids": [1]}
    result = AgentModelProjection(fields, frozenset({2}), [1])
    assert result.fields is fields
    assert result.deleted_model_ids == frozenset({2})
    assert result.availability_model_ids == [1]


def test_run_context_preserves_in_process_metadata_identity():
    metadata = object()
    context = AgentRunContext(metadata, False)
    assert context.metadata is metadata
    assert context.enable_memory is False
    with pytest.raises(FrozenInstanceError):
        context.enable_memory = True
