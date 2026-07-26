"""Unit tests for DashScopeModelProvider module.

Tests cover model fetching, type classification, error handling, and
the multi-bucket classification feature where one model can appear in
multiple categories (e.g., qwen3.7-plus in vlm, vlm3, and llm).
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from pytest_mock import MockFixture

import httpx

from backend.services.providers.dashscope_provider import (
    DashScopeModelProvider,
    _modality_set,
    _has_keyword,
    _is_dashscope_explicit_image_understanding_model,
    _is_dashscope_image_generation_model,
    _is_dashscope_video_understanding_model,
    _is_dashscope_image_understanding_model,
)


# =============================================================================
# Helper / unit function tests
# =============================================================================


class TestModalitySet:
    """Tests for _modality_set helper."""

    def test_none_returns_empty_set(self):
        assert _modality_set(None) == set()

    def test_empty_returns_empty_set(self):
        assert _modality_set([]) == set()

    def test_single_string_lowercased(self):
        assert _modality_set("Text") == {"text"}

    def test_list_of_strings_lowercased(self):
        assert _modality_set(["Text", "Image"]) == {"text", "image"}

    def test_mixed_case_normalized(self):
        assert _modality_set(["TEXT", "IMAGE"]) == {"text", "image"}

    def test_numeric_coerced_to_string(self):
        assert _modality_set([1, 2]) == {"1", "2"}


class TestHasKeyword:
    """Tests for _has_keyword helper."""

    def test_matches_single_keyword(self):
        assert _has_keyword("qwen-vl-plus", ("qwen-vl",)) is True

    def test_matches_any_keyword(self):
        assert _has_keyword("flux-model", ("image", "flux", "sdxl")) is True

    def test_keyword_not_found_returns_false(self):
        assert _has_keyword("qwen-turbo", ("image", "flux")) is False

    def test_empty_text_returns_false(self):
        assert _has_keyword("", ("flux",)) is False

    def test_substring_matching(self):
        """Keywords are matched as substrings (case-sensitive)."""
        assert _has_keyword("qwen-vl-plus", ("qwen-vl",)) is True
        assert _has_keyword("qwen-vl-plus", ("vl-plus",)) is True

    def test_substring_matching_case_sensitive(self):
        """Substring matching is case-sensitive: "qwen-vl" != "Qwen-VL"."""
        assert _has_keyword("Qwen-VL", ("qwen-vl",)) is False
        assert _has_keyword("qwen-vl", ("Qwen-VL",)) is False


class TestExplicitImageUnderstandingKeywords:
    """Tests for _is_dashscope_explicit_image_understanding_model."""

    @pytest.mark.parametrize("model_id,expected", [
        ("qwen-vl-plus", True),
        ("qwen2-vl-max", True),
        ("qwen2.5-vl-plus", True),
        ("qwen3-vl-plus", True),
        ("qwen3.5-vl-72b", True),
        ("qwen3.6-vl-72b-instruct", True),
        ("text-embedding-vl", True),
        ("vl-qwen-model", True),
        ("vision-model", True),
        ("visual-understanding", True),
        ("ocr-model", True),
        ("qwen3.6-27b", True),
        ("qwen-3.6-turbo", True),
        ("qwen-turbo", False),
        ("qwen-plus", False),
        ("embedding-model", False),
    ])
    def test_keyword_matching(self, model_id, expected):
        assert _is_dashscope_explicit_image_understanding_model(model_id) is expected


class TestImageGenerationDetection:
    """Tests for _is_dashscope_image_generation_model."""

    def test_explicit_vl_model_excluded(self):
        """Models that match explicit VL keywords are never image-gen."""
        assert _is_dashscope_image_generation_model(
            "qwen-vl-plus", "", set(), set()
        ) is False

    def test_image_in_response_modality(self):
        assert _is_dashscope_image_generation_model(
            "wanx-model", "", set(), {"image"}
        ) is True

    def test_image_generation_keyword_in_id(self):
        assert _is_dashscope_image_generation_model(
            "wanx-turbo", "", set(), set()
        ) is True

    def test_tryon_keyword(self):
        assert _is_dashscope_image_generation_model(
            "aitryon-tryon-v1", "", set(), set()
        ) is True

    def test_flux_keyword(self):
        assert _is_dashscope_image_generation_model(
            "flux-schnell", "", set(), set()
        ) is True

    def test_sdxl_keyword(self):
        assert _is_dashscope_image_generation_model(
            "sdxl-turbo", "", set(), set()
        ) is True

    def test_stable_diffusion_keyword(self):
        assert _is_dashscope_image_generation_model(
            "stable-diffusion-xl", "", set(), set()
        ) is True

    def test_plain_text_model_returns_false(self):
        assert _is_dashscope_image_generation_model(
            "qwen-turbo", "", {"text"}, {"text"}
        ) is False


class TestVideoUnderstandingDetection:
    """Tests for _is_dashscope_video_understanding_model."""

    def test_video_input_with_text_output(self):
        assert _is_dashscope_video_understanding_model(
            "model-x", "", {"video", "text"}, {"text"}
        ) is True

    def test_video_input_without_text_output(self):
        assert _is_dashscope_video_understanding_model(
            "model-x", "", {"video"}, set()
        ) is False

    def test_omni_keyword_in_id(self):
        assert _is_dashscope_video_understanding_model(
            "qwen-omni-turbo", "", set(), {"text"}
        ) is True

    def test_video_understanding_keyword_in_description(self):
        """Keywords in description match via substring (requires hyphen in "video-understanding")."""
        assert _is_dashscope_video_understanding_model(
            "some-model", "video-understanding model", set(), {"text"}
        ) is True
        assert _is_dashscope_video_understanding_model(
            "some-model", "uses video-ocr technology", set(), {"text"}
        ) is True

    def test_video_ocr_keyword(self):
        assert _is_dashscope_video_understanding_model(
            "video-ocr-v1", "", set(), {"text"}
        ) is True

    def test_text_only_model_returns_false(self):
        assert _is_dashscope_video_understanding_model(
            "qwen-turbo", "", {"text"}, {"text"}
        ) is False


class TestImageUnderstandingDetection:
    """Tests for _is_dashscope_image_understanding_model.

    Key invariant: this check is independent of video/generation checks.
    A model that qualifies as video-understanding can simultaneously qualify
    as image-understanding (e.g., qwen3.7-plus with Image+Video+Text input).
    """

    def test_image_input_with_text_output(self):
        assert _is_dashscope_image_understanding_model(
            "generic-model", "", {"image", "text"}, {"text"}
        ) is True

    def test_video_input_with_text_output_is_image_understanding(self):
        """Video input returning text is also image-understanding (vlm)."""
        assert _is_dashscope_image_understanding_model(
            "qwen3.7-plus", "", {"video", "text"}, {"text"}
        ) is True

    def test_explicit_vl_keyword_matches(self):
        """Models matching VL keywords qualify regardless of modality."""
        assert _is_dashscope_image_understanding_model(
            "qwen-vl-plus", "", set(), {"text"}
        ) is True

    def test_vision_keyword_in_id(self):
        assert _is_dashscope_image_understanding_model(
            "vision-model-v1", "", set(), {"text"}
        ) is True

    def test_ocr_keyword_in_id(self):
        assert _is_dashscope_image_understanding_model(
            "ocr-accurate-v2", "", set(), {"text"}
        ) is True

    def test_plain_text_model_excluded(self):
        """Pure text models do not qualify as image understanding."""
        assert _is_dashscope_image_understanding_model(
            "qwen-turbo", "", {"text"}, {"text"}
        ) is False

    def test_image_output_only_excluded(self):
        """Image-only output (no text in response) is not image understanding."""
        assert _is_dashscope_image_understanding_model(
            "wanx-turbo", "", {"text"}, {"image"}
        ) is False

    def test_no_video_or_image_in_input_excluded(self):
        """Models without image/video input do not qualify."""
        assert _is_dashscope_image_understanding_model(
            "generic-model", "", {"audio"}, {"text"}
        ) is False


# =============================================================================
# DashScopeModelProvider integration tests
# =============================================================================


class TestDashScopeModelProvider:
    """Tests for DashScopeModelProvider.get_models."""

    def _setup_mock_client(self, mocker, mock_response):
        """Set up mock for httpx.AsyncClient with proper context manager."""
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm,
        )
        return mock_cm

    # -------------------------------------------------------------------------
    # LLM (chat) tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_models_llm_success(self, mocker: MockFixture):
        """Pure text models are classified as llm."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "qwen-turbo",
                        "description": "Text generation model",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    },
                    {
                        "model": "qwen-plus",
                        "description": "Advanced text generation",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    },
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "llm",
            "api_key": "test-api-key",
        })

        assert len(result) == 2
        assert result[0]["id"] == "qwen-turbo"
        assert result[0]["model_type"] == "llm"
        assert result[0]["model_tag"] == "chat"
        assert result[0]["max_tokens"] == 4096

    @pytest.mark.asyncio
    async def test_get_models_llm_surfaces_capacity_hints(self, mocker: MockFixture):
        """Provider token metadata is returned as advisory capacity hints."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "qwen-plus",
                        "description": "Advanced text generation",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                            "context_length": 131072,
                            "max_output_tokens": "8192",
                            "tokenizer_family": "qwen",
                        },
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "llm",
            "api_key": "test-api-key",
        })

        assert result[0]["context_window_tokens"] == 131072
        assert result[0]["max_output_tokens"] == 8192
        assert result[0]["tokenizer_family"] == "qwen"
        assert result[0]["capacity_source"] == "provider_candidate"

    # -------------------------------------------------------------------------
    # VLM - image understanding tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_models_vlm_with_image_input(self, mocker: MockFixture):
        """Image+Text input models are classified as vlm."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "qwen-vl-plus",
                        "description": "Vision language model",
                        "inference_metadata": {
                            "request_modality": ["Image", "Text"],
                            "response_modality": ["Text"],
                        },
                    },
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "vlm",
            "api_key": "test-api-key",
        })

        assert len(result) == 1
        assert result[0]["id"] == "qwen-vl-plus"
        assert result[0]["model_type"] == "vlm"
        assert result[0]["model_tag"] == "chat"

    @pytest.mark.asyncio
    async def test_get_models_vlm_with_explicit_vl_keyword(self, mocker: MockFixture):
        """Models with explicit VL keywords are vlm even without modality fields."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "qwen-vl-max",
                        "description": "VL max model",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    },
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "vlm",
            "api_key": "test-api-key",
        })

        assert len(result) == 1
        assert result[0]["id"] == "qwen-vl-max"

    # -------------------------------------------------------------------------
    # VLM2 - image generation tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_models_vlm2_image_output(self, mocker: MockFixture):
        """Models with image in response_modality are classified as vlm2."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "wanx-turbo",
                        "description": "Image generation model",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Image"],
                        },
                    },
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "vlm2",
            "api_key": "test-api-key",
        })

        assert len(result) == 1
        assert result[0]["id"] == "wanx-turbo"
        assert result[0]["model_type"] == "vlm2"
        assert result[0]["model_tag"] == "chat"

    @pytest.mark.asyncio
    async def test_get_models_vlm2_image_keyword_in_id(self, mocker: MockFixture):
        """Image-gen models identified by keyword in model ID."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "flux-schnell",
                        "description": "Flux image model",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    },
                    {
                        "model": "qwen-turbo",
                        "description": "Text only",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    },
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "vlm2",
            "api_key": "test-api-key",
        })

        assert len(result) == 1
        assert result[0]["id"] == "flux-schnell"

    # -------------------------------------------------------------------------
    # VLM3 - video understanding tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_models_vlm3_video_input(self, mocker: MockFixture):
        """Models with video input are classified as vlm3."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "qwen-omni-turbo",
                        "description": "Video understanding model",
                        "inference_metadata": {
                            "request_modality": ["Video", "Text"],
                            "response_modality": ["Text"],
                        },
                    },
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "vlm3",
            "api_key": "test-api-key",
        })

        assert len(result) == 1
        assert result[0]["id"] == "qwen-omni-turbo"
        assert result[0]["model_type"] == "vlm3"
        assert result[0]["model_tag"] == "chat"

    @pytest.mark.asyncio
    async def test_get_models_vlm3_omni_keyword(self, mocker: MockFixture):
        """Models with 'omni' in model ID are vlm3 even without video modality."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "qwen3-omni-30b-a3b-instruct",
                        "description": "Omni multimodal model",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    },
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "vlm3",
            "api_key": "test-api-key",
        })

        assert len(result) == 1
        assert result[0]["id"] == "qwen3-omni-30b-a3b-instruct"

    # -------------------------------------------------------------------------
    # Multi-bucket classification (key new feature)
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_multibucket_video_model_also_appears_in_vlm(self, mocker: MockFixture):
        """A video-understanding model (Image+Video+Text input) appears in both vlm3 and vlm."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "qwen3.7-plus",
                        "description": "Multimodal model with video support",
                        "inference_metadata": {
                            "request_modality": ["Image", "Video", "Text"],
                            "response_modality": ["Text"],
                        },
                    },
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()

        vlm3_result = await provider.get_models({"model_type": "vlm3", "api_key": "test-key"})
        vlm_result = await provider.get_models({"model_type": "vlm", "api_key": "test-key"})
        llm_result = await provider.get_models({"model_type": "llm", "api_key": "test-key"})

        assert len(vlm3_result) == 1
        assert vlm3_result[0]["id"] == "qwen3.7-plus"
        assert vlm3_result[0]["model_type"] == "vlm3"

        assert len(vlm_result) == 1
        assert vlm_result[0]["id"] == "qwen3.7-plus"
        assert vlm_result[0]["model_type"] == "vlm"

        assert len(llm_result) == 1
        assert llm_result[0]["id"] == "qwen3.7-plus"
        assert llm_result[0]["model_type"] == "llm"

    @pytest.mark.asyncio
    async def test_multibucket_different_models_in_different_buckets(self, mocker: MockFixture):
        """Verify bucket isolation and correct cross-bucket membership.

        - qwen3.7-plus: video input → vlm3, also image input → vlm, also text → llm
        - qwen-turbo: text only → llm
        - wanx-turbo: image output (keyword) → vlm2; text input + text output → also llm
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "qwen3.7-plus",
                        "description": "Video + image model",
                        "inference_metadata": {
                            "request_modality": ["Video", "Text"],
                            "response_modality": ["Text"],
                        },
                    },
                    {
                        "model": "qwen-turbo",
                        "description": "Text only",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    },
                    {
                        "model": "wanx-turbo",
                        "description": "Image gen",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Image"],
                        },
                    },
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm,
        )

        provider = DashScopeModelProvider()

        vlm3_ids = {m["id"] for m in await provider.get_models({"model_type": "vlm3", "api_key": "k"})}
        vlm2_ids = {m["id"] for m in await provider.get_models({"model_type": "vlm2", "api_key": "k"})}
        llm_ids = {m["id"] for m in await provider.get_models({"model_type": "llm", "api_key": "k"})}

        assert vlm3_ids == {"qwen3.7-plus"}
        assert vlm2_ids == {"wanx-turbo"}
        assert llm_ids == {"qwen-turbo", "qwen3.7-plus", "wanx-turbo"}

    @pytest.mark.asyncio
    async def test_multibucket_model_copies_are_independent(self, mocker: MockFixture):
        """Model copies in different buckets must not share mutable state."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "qwen3.7-plus",
                        "description": "Multimodal model",
                        "inference_metadata": {
                            "request_modality": ["Video", "Text"],
                            "response_modality": ["Text"],
                        },
                    },
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        vlm3_result = await provider.get_models({"model_type": "vlm3", "api_key": "k"})
        vlm_result = await provider.get_models({"model_type": "vlm", "api_key": "k"})

        assert vlm3_result[0]["model_type"] == "vlm3"
        assert vlm_result[0]["model_type"] == "vlm"
        assert vlm3_result[0]["id"] == vlm_result[0]["id"]

    # -------------------------------------------------------------------------
    # Specialized types (exclusive - embedding / rerank / stt / tts)
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_models_embedding_by_id_keyword(self, mocker: MockFixture):
        """Embedding models identified by 'embedding' in model ID."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "text-embedding-v3",
                        "description": "Embedding model",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "embedding",
            "api_key": "test-api-key",
        })

        assert len(result) == 1
        assert result[0]["id"] == "text-embedding-v3"
        assert result[0]["model_type"] == "embedding"
        assert result[0]["model_tag"] == "embedding"

    @pytest.mark.asyncio
    async def test_get_models_embedding_by_chinese_description(self, mocker: MockFixture):
        """Embedding models also classified by Chinese description containing '向量'."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "embedding-v1",
                        "description": "向量embedding模型",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "embedding",
            "api_key": "test-api-key",
        })

        assert len(result) == 1
        assert result[0]["id"] == "embedding-v1"

    @pytest.mark.asyncio
    async def test_get_models_multi_embedding_returns_embedding_bucket(self, mocker: MockFixture):
        """multi_embedding request returns the same embedding bucket as embedding."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "text-embedding-multimodal-v3",
                        "description": "Multimodal embedding",
                        "inference_metadata": {
                            "request_modality": ["Text", "Image"],
                            "response_modality": ["Text"],
                        },
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "multi_embedding",
            "api_key": "test-api-key",
        })

        assert len(result) == 1
        assert result[0]["id"] == "text-embedding-multimodal-v3"
        assert result[0]["model_type"] == "embedding"

    @pytest.mark.asyncio
    async def test_get_models_rerank_by_id_keyword(self, mocker: MockFixture):
        """Rerank models identified by 'rerank' in model ID."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "gte-rerank",
                        "description": "Reranking model",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "rerank",
            "api_key": "test-api-key",
        })

        assert len(result) == 1
        assert result[0]["id"] == "gte-rerank"
        assert result[0]["model_type"] == "rerank"
        assert result[0]["model_tag"] == "rerank"

    @pytest.mark.asyncio
    async def test_get_models_rerank_by_chinese_description(self, mocker: MockFixture):
        """Rerank models also classified by Chinese description containing '重排序'."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "rerank-v1",
                        "description": "重排序模型",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "rerank",
            "api_key": "test-api-key",
        })

        assert len(result) == 1
        assert result[0]["id"] == "rerank-v1"

    @pytest.mark.asyncio
    async def test_get_models_stt_success(self, mocker: MockFixture):
        """Audio input with Text output is classified as stt."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "paraformer-realtime-v2",
                        "description": "Speech recognition",
                        "inference_metadata": {
                            "request_modality": ["Audio"],
                            "response_modality": ["Text"],
                        },
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "stt",
            "api_key": "test-api-key",
        })

        assert len(result) == 1
        assert result[0]["id"] == "paraformer-realtime-v2"
        assert result[0]["model_type"] == "stt"
        assert result[0]["model_tag"] == "stt"

    @pytest.mark.asyncio
    async def test_get_models_tts_success(self, mocker: MockFixture):
        """Audio output without Video is classified as tts."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "sambert-tts",
                        "description": "Text to speech",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Audio"],
                        },
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "tts",
            "api_key": "test-api-key",
        })

        assert len(result) == 1
        assert result[0]["id"] == "sambert-tts"
        assert result[0]["model_type"] == "tts"
        assert result[0]["model_tag"] == "tts"

    @pytest.mark.asyncio
    async def test_get_models_tts_excludes_video_audio_output(self, mocker: MockFixture):
        """Audio+Video response modality is excluded from tts (goes to stt)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "omni-audio-video-model",
                        "description": "Audio and video output",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Audio", "Video"],
                        },
                    },
                    {
                        "model": "pure-audio-tts",
                        "description": "Audio only output",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Audio"],
                        },
                    },
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "tts",
            "api_key": "test-api-key",
        })

        assert len(result) == 1
        assert result[0]["id"] == "pure-audio-tts"

    # -------------------------------------------------------------------------
    # Pagination
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_models_pagination(self, mocker: MockFixture):
        """Pagination correctly merges pages until models < page_size."""
        mock_response_page1 = MagicMock()
        mock_response_page1.status_code = 200
        mock_response_page1.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": f"model-{i}",
                        "description": "test",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    }
                    for i in range(100)
                ]
            }
        }
        mock_response_page1.raise_for_status = MagicMock()

        mock_response_page2 = MagicMock()
        mock_response_page2.status_code = 200
        mock_response_page2.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": f"model-{i}",
                        "description": "test",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    }
                    for i in range(100, 150)
                ]
            }
        }
        mock_response_page2.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.side_effect = [mock_response_page1, mock_response_page2]

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm,
        )

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "llm",
            "api_key": "test-api-key",
        })

        assert len(result) == 150

    # -------------------------------------------------------------------------
    # Error handling
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_models_empty_response(self, mocker: MockFixture):
        """Empty model list from API returns empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"output": {"models": []}}
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "llm",
            "api_key": "test-api-key",
        })

        assert result == []

    @pytest.mark.asyncio
    async def test_get_models_http_error(self, mocker: MockFixture):
        """HTTP error returns error dict with connection_failed code."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm,
        )

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "llm",
            "api_key": "test-api-key",
        })

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["_error"] == "connection_failed"

    @pytest.mark.asyncio
    async def test_get_models_connect_error(self, mocker: MockFixture):
        """ConnectError returns error dict."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection failed")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm,
        )

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "llm",
            "api_key": "test-api-key",
        })

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["_error"] == "connection_failed"

    @pytest.mark.asyncio
    async def test_get_models_timeout(self, mocker: MockFixture):
        """ConnectTimeout returns error dict."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectTimeout("Timeout")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm,
        )

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "llm",
            "api_key": "test-api-key",
        })

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["_error"] == "connection_failed"

    @pytest.mark.asyncio
    async def test_get_models_rate_limit_retry(self, mocker: MockFixture):
        """429 response triggers retry after sleeping."""
        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429

        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "qwen-turbo",
                        "description": "Text generation",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    }
                ]
            }
        }
        ok_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.side_effect = [rate_limit_response, ok_response]

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm,
        )
        mocker.patch(
            "backend.services.providers.dashscope_provider.asyncio.sleep",
            new=AsyncMock(),
        )

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "llm",
            "api_key": "test-api-key",
        })

        assert mock_client.get.call_count == 2
        assert len(result) == 1
        assert result[0]["id"] == "qwen-turbo"

    @pytest.mark.asyncio
    async def test_get_models_authorization_header(self, mocker: MockFixture):
        """Authorization header is correctly set from api_key."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "qwen-turbo",
                        "description": "Test",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm,
        )

        provider = DashScopeModelProvider()
        await provider.get_models({
            "model_type": "llm",
            "api_key": "my-secret-key",
        })

        call_args = mock_client.get.call_args
        headers = call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer my-secret-key"

    @pytest.mark.asyncio
    async def test_get_models_unknown_type_returns_empty(self, mocker: MockFixture):
        """Unknown model type returns empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "qwen-turbo",
                        "description": "Text generation",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "unknown_type",
            "api_key": "test-api-key",
        })

        assert result == []

    @pytest.mark.asyncio
    async def test_get_models_id_case_insensitive(self, mocker: MockFixture):
        """Model IDs are lowercased during classification."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "Qwen-VL-Plus",
                        "description": "VL model",
                        "inference_metadata": {
                            "request_modality": ["Image", "Text"],
                            "response_modality": ["Text"],
                        },
                    },
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "vlm",
            "api_key": "test-api-key",
        })

        assert len(result) == 1
        assert result[0]["id"] == "qwen-vl-plus"

    @pytest.mark.asyncio
    async def test_get_models_stores_canonical_fields(self, mocker: MockFixture):
        """Canonical fields (object, owned_by, created) are set from raw model."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "qwen-turbo",
                        "object": "chat.completion",
                        "owned_by": "Alibaba",
                        "description": "Test",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    },
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "llm",
            "api_key": "test-api-key",
        })

        assert result[0]["object"] == "chat.completion"
        assert result[0]["owned_by"] == "Alibaba"
        assert result[0]["created"] == 0

    @pytest.mark.asyncio
    async def test_get_models_defaults_object_and_owned_by(self, mocker: MockFixture):
        """object and owned_by default when not in raw model."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "qwen-turbo",
                        "description": "Test",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"],
                        },
                    },
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        self._setup_mock_client(mocker, mock_response)

        provider = DashScopeModelProvider()
        result = await provider.get_models({
            "model_type": "llm",
            "api_key": "test-api-key",
        })

        assert result[0]["object"] == "model"
        assert result[0]["owned_by"] == "dashscope"
