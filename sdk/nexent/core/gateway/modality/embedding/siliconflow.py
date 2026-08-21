"""SiliconFlow multimodal embedding adapter."""

from __future__ import annotations

import base64
import os

from ...multimodal_adapter import ModelInfo
from ...registry import register_adapter
from .embedding_adapter import ASSETS_DIR, _detect_image_mime, _MultimodalEmbeddingAdapter


@register_adapter("siliconflow", "multi_embedding")
class SiliconflowEmbeddingAdapter(_MultimodalEmbeddingAdapter):
    """SiliconFlow multimodal embedding adapter.

    Attributes:
        factory: ``"siliconflow"``.
    """

    factory = "siliconflow"

    def _prepare_multimodal_input(self, inputs):
        """Build the SiliconFlow multimodal request body."""
        prepared = []
        for item in inputs:
            if "text" in item:
                prepared.append(item["text"])
            elif "image" in item:
                img = item["image"]
                if isinstance(img, bytes):
                    mime = _detect_image_mime(img)
                    img = f"data:{mime};base64,{base64.b64encode(img).decode('utf-8')}"
                prepared.append({"image": img})
            else:
                prepared.append(item)
        return {"model": self._model_name, "input": prepared}

    def _extract_embeddings(self, response):
        """Extract embedding vectors from a SiliconFlow response."""
        return [item["embedding"] for item in response["data"]]

    def _test_inputs(self):
        """Return sample text + raw image-bytes inputs for connectivity checks."""
        test_image_path = os.path.join(ASSETS_DIR, "test.png")
        with open(test_image_path, "rb") as f:
            image_data = f.read()
        return [
            {"text": "Hello, nexent!"},
            {"image": image_data},
        ]

    def get_model_info(self) -> ModelInfo:
        """Return ``ModelInfo`` with text + multimodal capabilities."""
        return ModelInfo(self._context.model_name, self._context.display_name or "", self.factory, {"text": True, "multimodal": True})
