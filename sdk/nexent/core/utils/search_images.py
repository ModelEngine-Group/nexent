# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Publish the common web-search image event through an injected runtime callable."""

import json
import logging

from .observer import ProcessType


logger = logging.getLogger(__name__)


def publish_filtered_images(observer, image_filterer, urls, query):
    if not callable(image_filterer):
        raise ValueError("Web image filtering requires image_filterer")
    try:
        selected = image_filterer(urls, query)
    except Exception as error:
        # Preserve the existing whole-batch failure event; do not retry the batch.
        logger.info("image_filter_batch_failed exception_type=%s", type(error).__name__)
        selected = urls
    if observer:
        observer.add_message("", ProcessType.PICTURE_WEB, json.dumps({"images_url": selected}, ensure_ascii=False))
