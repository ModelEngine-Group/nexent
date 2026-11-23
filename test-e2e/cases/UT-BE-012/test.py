"""D1 backend unit contracts derived from the functional baseline.

These tests import production modules directly and never import Nexent's old
``test`` package. External services and databases are replaced at the module
boundary; assertions describe user-visible policy, not implementation calls.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException


STAGE = pytest.mark.stage("D1")






def _profile(version: str = "2026-01") -> SimpleNamespace:
    return SimpleNamespace(
        context_window_tokens=128_000,
        max_input_tokens=120_000,
        max_output_tokens=8_000,
        default_output_reserve_tokens=4_000,
        tokenizer_family="openai",
        capability_profile_version=version,
    )




















@STAGE
@pytest.mark.case_id("UT-BE-012")
def test_datamate_url_normalization_and_parts_builder() -> None:
    from apps.file_management_app import (
        _build_datamate_url_from_parts,
        _ensure_http_scheme,
        _normalize_datamate_download_url,
    )

    with pytest.raises(HTTPException, match="must start with http"):
        _ensure_http_scheme("host:8080")
    assert _build_datamate_url_from_parts("https://host", "ds 1", "f-1") == (
        "https://host/api/data-management/datasets/ds 1/files/f-1/download"
    )
    normalized = _normalize_datamate_download_url(
        "https://host/api/data-management/datasets/ds/files/file?token=secret#fragment"
    )
    assert normalized == "https://host/api/data-management/datasets/ds/files/file/download"
    with pytest.raises(HTTPException) as invalid:
        _normalize_datamate_download_url("https://host/not-datamate")
    assert invalid.value.status_code == 400
