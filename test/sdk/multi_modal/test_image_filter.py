# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-SDK-DPR-IMAGE-01/02/03: preserve the extracted image decision contract."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from nexent.multi_modal.image_filter import ImageImportanceFilter
from PIL import Image


@pytest.fixture
def clip(mocker):
    model = MagicMock()
    processor = MagicMock(return_value={"pixel_values": "pixels"})
    logits = model.return_value.logits_per_image
    logits.softmax.return_value.__getitem__ = MagicMock(
        return_value=SimpleNamespace(tolist=lambda: [0.1, 0.9]),
    )
    transformers = SimpleNamespace(
        CLIPModel=SimpleNamespace(from_pretrained=MagicMock(return_value=model)),
        CLIPProcessor=SimpleNamespace(from_pretrained=MagicMock(return_value=processor)),
    )
    torch = SimpleNamespace(no_grad=MagicMock(side_effect=nullcontext))
    mocker.patch.dict("sys.modules", {"transformers": transformers, "torch": torch})
    return SimpleNamespace(
        model=model, processor=processor, logits=logits, loaders=transformers, torch=torch,
    )


@pytest.mark.parametrize("size,expected", [((199, 300), False), ((300, 199), False), ((200, 200), True)])
def test_size_and_disabled_filter_never_load_models(clip, size, expected):
    scorer = ImageImportanceFilter("/models/clip")
    with Image.new("RGB", size) as image:
        result = scorer.filter(image, enabled=False)
    assert result == {
        "is_important": expected, "confidence": float(expected),
        "probabilities": {"positive": float(expected), "negative": 0.0},
    }
    clip.loaders.CLIPModel.from_pretrained.assert_not_called()
    clip.processor.assert_not_called()


def test_missing_or_small_image_never_loads_models(clip):
    scorer = ImageImportanceFilter("/models/clip")
    with Image.new("RGB", (199, 200)) as image:
        for value in (None, image):
            assert scorer.filter(value, enabled=True) == {
                "is_important": False, "confidence": 0.0,
                "probabilities": {"positive": 0.0, "negative": 0.0},
            }
    clip.loaders.CLIPModel.from_pretrained.assert_not_called()


@pytest.mark.parametrize("negative,positive,expected", [
    (0.1, 0.9, True), (0.4, 0.6, False), (0.5, 0.7, False), (0.49, 0.61, True),
])
def test_clip_thresholds_prompt_order_and_model_reuse(clip, negative, positive, expected):
    clip.logits.softmax.return_value.__getitem__.return_value = SimpleNamespace(
        tolist=lambda: [negative, positive],
    )
    scorer = ImageImportanceFilter("/models/clip")
    with Image.new("RGB", (200, 200)) as image:
        for _ in range(2):
            assert scorer.filter(image, enabled=True, positive_prompt="keep", negative_prompt="discard") == {
                "is_important": expected, "confidence": positive,
                "probabilities": {"positive": positive, "negative": negative},
            }
        assert image.getpixel((0, 0)) == (0, 0, 0)
        assert clip.processor.call_args.kwargs == {
            "text": ["discard", "keep"], "images": image, "return_tensors": "pt", "padding": True,
        }
    clip.loaders.CLIPModel.from_pretrained.assert_called_once_with("/models/clip")
    clip.loaders.CLIPProcessor.from_pretrained.assert_called_once_with("/models/clip")
    assert clip.model.call_count == 2
    clip.model.assert_called_with(pixel_values="pixels")
    clip.logits.softmax.assert_called_with(dim=1)
    assert clip.torch.no_grad.call_count == 2


@pytest.mark.parametrize("loader", ["CLIPModel", "CLIPProcessor"])
def test_load_failure_uses_only_existing_size_result_without_retry(clip, loader):
    getattr(clip.loaders, loader).from_pretrained.side_effect = RuntimeError("unavailable")
    scorer = ImageImportanceFilter("/models/clip")
    with Image.new("RGB", (200, 200)) as image:
        assert scorer.filter(image, enabled=True) == {
            "is_important": True, "confidence": 1.0,
            "probabilities": {"positive": 1.0, "negative": 0.0},
        }
    clip.loaders.CLIPModel.from_pretrained.assert_called_once()
    assert clip.loaders.CLIPProcessor.from_pretrained.call_count == (loader == "CLIPProcessor")
    clip.model.assert_not_called()
    clip.processor.assert_not_called()


@pytest.mark.parametrize("stage", ["processor", "model", "softmax"])
def test_inference_failure_keeps_existing_result_and_never_retries(clip, stage):
    target = clip.logits.softmax if stage == "softmax" else getattr(clip, stage)
    target.side_effect = RuntimeError("inference unavailable")
    scorer = ImageImportanceFilter("/models/clip")
    with Image.new("RGB", (200, 200)) as image:
        assert scorer.filter(image, enabled=True) == {
            "is_important": True, "confidence": 0.8,
            "probabilities": {"positive": 0.8, "negative": 0.2},
        }
    target.assert_called_once()
    clip.loaders.CLIPModel.from_pretrained.assert_called_once()


@pytest.mark.parametrize("mode,expected", [("RGBA", (255, 255, 255)), ("L", (0, 0, 0))])
def test_converted_image_closed_but_caller_image_stays_open(clip, mode, expected):
    seen = []

    def process(**kwargs):
        converted = kwargs["images"]
        assert converted.mode == "RGB"
        assert converted.getpixel((0, 0)) == expected
        seen.append(converted)
        return {"pixel_values": "pixels"}

    clip.processor.side_effect = process
    with Image.new(mode, (200, 200)) as image:
        ImageImportanceFilter("/models/clip").filter(image, enabled=True)
        image.getpixel((0, 0))
        with pytest.raises(ValueError, match="closed image"):
            seen[0].getpixel((0, 0))


def test_conversion_failure_propagates_without_inference(clip, mocker):
    with Image.new("RGBA", (200, 200)) as image:
        mocker.patch("nexent.multi_modal.image_filter.Image.new", side_effect=ValueError("convert"))
        with pytest.raises(ValueError, match="convert"):
            ImageImportanceFilter("/models/clip").filter(image, enabled=True)
    clip.processor.assert_not_called()
    clip.model.assert_not_called()
