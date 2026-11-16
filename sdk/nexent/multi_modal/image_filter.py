# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Image importance decisions without transport, storage or deployment configuration."""

import logging

from PIL import Image


logger = logging.getLogger(__name__)


class ImageImportanceFilter:
    """Own lazily loaded CLIP components; callers own input images and execution."""

    def __init__(self, model_path: str):
        self.model_path = model_path
        self.model = None
        self.processor = None
        self.clip_available = False

    def _init_clip_model(self):
        if self.clip_available:
            return
        self.model = None
        self.processor = None
        try:
            from transformers import CLIPModel, CLIPProcessor

            self.model = CLIPModel.from_pretrained(self.model_path)
            self.processor = CLIPProcessor.from_pretrained(self.model_path)
            self.clip_available = True
        except Exception as error:
            logger.warning("clip_load_failed exception_type=%s", type(error).__name__)

    @staticmethod
    def check_image_size(width: int, height: int, min_width: int = 200, min_height: int = 200) -> bool:
        return width >= min_width and height >= min_height

    def filter(
        self, image: Image.Image | None, *, enabled: bool,
        positive_prompt: str = "an important image", negative_prompt: str = "an unimportant image",
    ) -> dict:
        """Preserve the existing size gate, CLIP threshold and failure results."""
        if image is None or not self.check_image_size(image.width, image.height):
            return {"is_important": False, "confidence": 0.0,
                    "probabilities": {"positive": 0.0, "negative": 0.0}}
        if not enabled:
            return {"is_important": True, "confidence": 1.0,
                    "probabilities": {"positive": 1.0, "negative": 0.0}}
        if not self.clip_available:
            self._init_clip_model()
        if not self.clip_available:
            return {"is_important": True, "confidence": 1.0,
                    "probabilities": {"positive": 1.0, "negative": 0.0}}

        converted = None
        try:
            if image.mode == "RGBA":
                converted = Image.new("RGB", image.size, (255, 255, 255))
                alpha = image.getchannel("A")
                try:
                    converted.paste(image, mask=alpha)
                finally:
                    alpha.close()
            elif image.mode != "RGB":
                converted = image.convert("RGB")
            try:
                import torch

                inputs = self.processor(
                    text=[negative_prompt, positive_prompt], images=converted if converted is not None else image,
                    return_tensors="pt", padding=True,
                )
                with torch.no_grad():
                    outputs = self.model(**inputs)
                negative, positive = outputs.logits_per_image.softmax(dim=1)[0].tolist()
                return {
                    "is_important": bool(positive > 0.6 and negative < 0.5),
                    "confidence": float(positive),
                    "probabilities": {"positive": float(positive), "negative": float(negative)},
                }
            except Exception as error:
                # This size-only result is the pre-existing data-process behavior.
                logger.warning("clip_inference_failed exception_type=%s", type(error).__name__)
                return {"is_important": True, "confidence": 0.8,
                        "probabilities": {"positive": 0.8, "negative": 0.2}}
        finally:
            if converted is not None:
                converted.close()
