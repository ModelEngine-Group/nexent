import pytest

from consts.capability_profiles import CATALOG_REVISION
from services.model_capacity_catalog_service import (
    catalog_status,
    refresh_catalog_candidate,
    stage_trusted_candidate,
)


def valid_document():
    return {
        "revision": "2099-01-01.1",
        "profiles": {
            "test/model@1": {
                "provider": "test", "model_name": "model",
                "context_window_tokens": 1000, "max_output_tokens": 100,
                "verified_at": "2098-12-31T00:00:00Z", "evidence": ["signed-evidence-id"],
            }
        },
    }


def test_untrusted_candidate_is_rejected():
    with pytest.raises(ValueError, match="catalog_source_untrusted"):
        stage_trusted_candidate(valid_document(), source_identity="official", signature_verified=False)


@pytest.mark.parametrize("mutation", ["missing_evidence", "invalid_capacity", "same_revision"])
def test_invalid_candidate_is_not_staged(mutation):
    doc = valid_document()
    if mutation == "missing_evidence": doc["profiles"]["test/model@1"]["evidence"] = []
    if mutation == "invalid_capacity": doc["profiles"]["test/model@1"]["max_output_tokens"] = 1000
    if mutation == "same_revision": doc["revision"] = CATALOG_REVISION
    with pytest.raises(ValueError):
        stage_trusted_candidate(doc, source_identity="official", signature_verified=True)


def test_refresh_stages_diff_without_changing_active_catalog():
    before = catalog_status()["active_revision"]
    candidate = refresh_catalog_candidate(
        valid_document, source_identity="nexent-official",
        verifier=lambda document: document["revision"] == "2099-01-01.1",
    )
    after = catalog_status()
    assert candidate.added == ("test/model@1",)
    assert after["candidate"]["revision"] == "2099-01-01.1"
    assert after["active_revision"] == before == CATALOG_REVISION
