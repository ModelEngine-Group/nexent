"""DashScope multimodal embedding adapter."""

from __future__ import annotations

import base64
import os

from ...multimodal_adapter import ModelInfo
from ...registry import register_adapter
from .embedding_adapter import ASSETS_DIR, _MultimodalEmbeddingAdapter


@register_adapter("dashscope", "multi_embedding")
class DashScopeEmbeddingAdapter(_MultimodalEmbeddingAdapter):
    """DashScope multimodal embedding adapter.

    Attributes:
        factory: ``"dashscope"``.
    """

    factory = "dashscope"

    def _prepare_multimodal_input(self, inputs):
        """Build the DashScope multimodal request body."""
        normalized = []
        for item in inputs:
            if "image" in item:
                img = item["image"]
                if isinstance(img, bytes):
                    img = f"data:image/png;base64,{base64.b64encode(img).decode('utf-8')}"
                normalized.append({"image": img})
            else:
                normalized.append(item)
        return {"model": self._model_name, "input": {"contents": normalized}}

    def _extract_embeddings(self, response):
        """Extract embedding vectors from a DashScope response."""
        return [item["embedding"] for item in response["output"]["embeddings"]]

    def _test_inputs(self):
        """Return sample text + image inputs for connectivity checks."""
        test_image_path = os.path.join(ASSETS_DIR, "test.png")
        with open(test_image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        return [
            {"text": "Hello, nexent!"},
            {"image": f"data:image/png;base64,{image_data}"},
        ]

    def get_model_info(self) -> ModelInfo:
        """Return ``ModelInfo`` with text + multimodal capabilities."""
        return ModelInfo(self._context.model_name, self._context.display_name or "", self.factory, {"text": True, "multimodal": True})
