"""Unit tests for the AIDP knowledge base page refactor service helpers.

Covers the legacy implementation helpers for defaults, chunk mode, overlap
conversion, and graph configuration validation and serialization.
"""

import json

import pytest

from consts.exceptions import AppException
from ext_components.aidp.services.aidp_service import (
    _apply_create_defaults,
    _serialize_graph_config,
    _validate_chunking,
)


class TestSerializeGraphConfig:
    """The structured graph form is validated here and serialized for AIDP."""

    def test_serializes_documented_keys(self):
        result = _serialize_graph_config(
            {
                "domain": "medical",
                "retrieve_default_topk": 7,
                "retrieve_subgraph_hop": 3,
                "no_think_mode": False,
                "prompt_language": "english",
                "prompt_text": "extract entities",
                "synonym_merge_enable": True,
                "disambiguation_enable": True,
            }
        )

        assert json.loads(result) == {
            "domain": "medical",
            "retrieve_default_topk": 7,
            "retrieve_subgraph_hop": 3,
            "no_think_mode": False,
            "prompt_language": "english",
            "prompt_text": "extract entities",
            "synonym_merge_enable": True,
            "disambiguation_enable": True,
        }

    def test_applies_documented_defaults(self):
        payload = json.loads(_serialize_graph_config({}))

        assert payload["domain"] == "general"
        assert payload["retrieve_default_topk"] == 5
        assert payload["retrieve_subgraph_hop"] == 2
        assert payload["no_think_mode"] is True
        assert payload["prompt_language"] == "chinese"
        assert payload["prompt_text"] == ""
        assert payload["synonym_merge_enable"] is False
        assert payload["disambiguation_enable"] is False

    def test_ignores_unknown_keys(self):
        payload = json.loads(_serialize_graph_config({"unexpected": "value"}))

        assert "unexpected" not in payload

    def test_rejects_unknown_domain(self):
        with pytest.raises(AppException):
            _serialize_graph_config({"domain": "legal"})

    def test_rejects_unknown_prompt_language(self):
        with pytest.raises(AppException):
            _serialize_graph_config({"prompt_language": "french"})

    def test_rejects_non_string_prompt(self):
        with pytest.raises(AppException):
            _serialize_graph_config({"prompt_text": 123})

    def test_rejects_prompt_over_byte_limit(self):
        # 700 Chinese characters are 2100 UTF-8 bytes, above the 2048 limit.
        with pytest.raises(AppException):
            _serialize_graph_config({"prompt_text": "中" * 700})

    def test_accepts_prompt_at_byte_limit(self):
        prompt = "中" * 682  # 2046 bytes

        payload = json.loads(_serialize_graph_config({"prompt_text": prompt}))

        assert payload["prompt_text"] == prompt

    @pytest.mark.parametrize("value", [0, 101, "5", True])
    def test_rejects_invalid_candidate_topk(self, value):
        with pytest.raises(AppException):
            _serialize_graph_config({"retrieve_default_topk": value})

    @pytest.mark.parametrize("value", [0, 4, "2", True])
    def test_rejects_invalid_hop_count(self, value):
        with pytest.raises(AppException):
            _serialize_graph_config({"retrieve_subgraph_hop": value})


class TestValidateChunking:
    """The overlap must stay within half of the chunk size."""

    def test_accepts_existing_default_pair(self):
        _validate_chunking({"chunk_token_num": 1024, "chunk_overlap_num": 128})

    def test_accepts_exact_half(self):
        _validate_chunking({"chunk_token_num": 512, "chunk_overlap_num": 256})

    def test_rejects_overlap_above_half(self):
        with pytest.raises(AppException):
            _validate_chunking({"chunk_token_num": 512, "chunk_overlap_num": 300})

    def test_rejects_negative_overlap(self):
        with pytest.raises(AppException):
            _validate_chunking({"chunk_token_num": 1024, "chunk_overlap_num": -1})

    @pytest.mark.parametrize("tokens", [0, -5])
    def test_skips_non_positive_chunk_size(self, tokens):
        # A non-positive chunk size is the upstream contract's business and the
        # ratio cannot be evaluated against it.
        _validate_chunking({"chunk_token_num": tokens, "chunk_overlap_num": 128})

    def test_skips_when_chunk_size_is_missing(self):
        _validate_chunking({"chunk_overlap_num": 128})

    def test_skips_non_integer_values(self):
        _validate_chunking({"chunk_token_num": "1024", "chunk_overlap_num": "128"})


class TestApplyCreateDefaults:
    """Creation defaults and chunk mode survive the merge."""

    def test_fills_chunk_mode_and_graph_defaults(self):
        result = _apply_create_defaults({"name": "kb"})

        assert result["chunk_mode"] == 0
        assert result["is_exist_graph"] is False
        assert result["chunk_token_num"] == 1024
        assert result["chunk_overlap_num"] == 128
        assert result["topk"] == 10
        assert result["similarity"] == 0.0
        assert result["embedding_model"] == "default"
        assert result["caption_enable"] == 0

    def test_keeps_legal_chunk_mode(self):
        result = _apply_create_defaults({"name": "kb", "chunk_mode": 1})

        assert result["chunk_mode"] == 1

    def test_disabled_graph_drops_graph_fields(self):
        result = _apply_create_defaults(
            {
                "name": "kb",
                "is_exist_graph": False,
                "graph_config": {"domain": "medical"},
                "llm_model_name": "llm-a",
            }
        )

        assert "graph_config" not in result
        assert "llm_model_name" not in result

    def test_enabled_graph_serializes_configuration(self):
        result = _apply_create_defaults(
            {
                "name": "kb",
                "is_exist_graph": True,
                "graph_config": {"domain": "finance", "no_think_mode": False},
                "llm_model_name": "llm-a",
            }
        )

        assert isinstance(result["graph_config"], str)
        graph_config = json.loads(result["graph_config"])
        assert graph_config["domain"] == "finance"
        assert graph_config["llm_model_name"] == "llm-a"
        assert "llm_model_name" not in result

    def test_enabled_graph_without_config_is_left_alone(self):
        result = _apply_create_defaults({"name": "kb", "is_exist_graph": True})

        assert "graph_config" not in result

    def test_rejects_invalid_overlap_ratio(self):
        with pytest.raises(AppException):
            _apply_create_defaults(
                {"name": "kb", "chunk_token_num": 512, "chunk_overlap_num": 300}
            )
