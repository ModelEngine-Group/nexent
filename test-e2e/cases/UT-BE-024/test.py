"""D1 backend policy tests for repository, sharing, runtime and memory."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


STAGE = pytest.mark.stage("D1")
























@STAGE
@pytest.mark.case_id("UT-BE-024")
def test_runtime_metadata_is_canonical_and_cannot_merge_non_json_values() -> None:
    from utils.runtime_metadata_utils import canonical_runtime_metadata_json, validate_runtime_metadata

    left = {"z": 1, "nested": {"b": 2, "a": 1}}
    right = {"nested": {"a": 1, "b": 2}, "z": 1}
    assert canonical_runtime_metadata_json(left) == canonical_runtime_metadata_json(right)
    assert validate_runtime_metadata(left) == left
    with pytest.raises(ValueError):
        validate_runtime_metadata({"unsafe": object()})


