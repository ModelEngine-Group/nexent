from __future__ import annotations

import logging

import pytest

from services.agent_repository_service import (
    _normalize_listing_tags,
    _validate_card_fields,
)

pytestmark = [
    pytest.mark.case_id("UT-BE-AUTO-1B0108BB27372242"),
    pytest.mark.stage("D1"),
]


def test_card_field_validation_and_tag_normalization(caplog):
    with caplog.at_level(logging.WARNING, logger="agent_repository_service"):
        assert _normalize_listing_tags([" ai ", "coding", "ai", ""]) == [
            "ai",
            "coding",
        ]

        assert _normalize_listing_tags(["single"]) == ["single"]
        five_tags = ["t1", "t2", "t3", "t4", "t5"]
        assert _normalize_listing_tags(five_tags) == five_tags
        with pytest.raises(ValueError, match="tags must contain at most 5 items"):
            _normalize_listing_tags(["t1", "t2", "t3", "t4", "t5", "t6"])

        tag_20 = "a" * 20
        assert _normalize_listing_tags([tag_20]) == [tag_20]
        with pytest.raises(
            ValueError, match="Each tag must be at most 20 characters"
        ):
            _normalize_listing_tags(["a" * 21])

        with pytest.raises(ValueError, match="tags must be a list of strings"):
            _normalize_listing_tags("not-a-list")
        with pytest.raises(ValueError, match="tags must be a list of strings"):
            _normalize_listing_tags(None)
        with pytest.raises(ValueError, match="tags must be a list of strings"):
            _normalize_listing_tags(["ok", 1])
        with pytest.raises(
            ValueError, match="tags must contain at least one non-empty tag"
        ):
            _normalize_listing_tags(["", "  ", "\t"])

        repository_data = {"icon": "🤖", "tags": ["a", "b"]}
        assert _validate_card_fields(repository_data) is None
        assert repository_data["tags"] == ["a", "b"]

        normalized_card = {"icon": "🤖", "tags": [" A ", "b", "A", ""]}
        _validate_card_fields(normalized_card)
        assert normalized_card["tags"] == ["A", "b"]

        for bad_icon in (None, "", "   "):
            with pytest.raises(
                ValueError,
                match="icon is required and must be a non-empty string",
            ):
                _validate_card_fields({"icon": bad_icon, "tags": ["a"]})
        with pytest.raises(
            ValueError,
            match="icon is required and must be a non-empty string",
        ):
            _validate_card_fields({"tags": ["a"]})

        icon_32 = "i" * 32
        _validate_card_fields({"icon": icon_32, "tags": ["a"]})
        with pytest.raises(
            ValueError, match="icon must be at most 32 characters"
        ):
            _validate_card_fields({"icon": "i" * 33, "tags": ["a"]})

        with pytest.raises(
            ValueError,
            match="tags is required for marketplace listing submission",
        ):
            _validate_card_fields({"icon": "🤖"})

    secret_markers = ("api_key", "api key", "access_key", "token", "password", "secret")
    for record in caplog.records:
        message = record.getMessage().lower()
        assert not any(marker in message for marker in secret_markers), message
