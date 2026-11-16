# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime-owned image filtering inside the existing managed tool execution."""

import asyncio
import logging
from functools import cache
from threading import Lock
from time import monotonic

import aiohttp
from contracts.constants import environment
from nexent.core.concurrency import get_current_thread_manager
from nexent.multi_modal.image_filter import ImageImportanceFilter

from infrastructure.web_images import load_web_image

logger = logging.getLogger(__name__)
_NEGATIVE_PROMPT = "logo or banner or background or advertisement or icon or avatar"


class WebImageFilter:
    def __init__(self, *, enabled: bool, model_path: str | None, image_seconds: float = 2):
        self.enabled = enabled
        self.scorer = ImageImportanceFilter(model_path)
        self.image_seconds = image_seconds
        self._model_lock = Lock()

    def __call__(self, urls: list[str], query: str) -> list[str]:
        if get_current_thread_manager() is None:
            raise RuntimeError("Web image filtering requires managed tool execution")
        # SDK search tools are synchronous and already execute on a managed worker.
        return asyncio.run(self._filter(urls, query))

    async def _filter(self, urls, query, *, image_loader=None, event_prefix="web_image"):
        loader = load_web_image if image_loader is None else image_loader
        semaphore = asyncio.Semaphore(10)
        timeout = aiohttp.ClientTimeout(total=self.image_seconds)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async def one(url):
                async with semaphore:
                    image = None
                    deadline = monotonic() + self.image_seconds
                    try:
                        async with asyncio.timeout(self.image_seconds):
                            image = await loader(session, url)
                            if image is None:
                                return None
                            remaining = deadline - monotonic()
                            if remaining <= 0 or not self._model_lock.acquire(timeout=remaining):
                                raise TimeoutError()
                            try:
                                result = self.scorer.filter(
                                    image, enabled=self.enabled, positive_prompt=query,
                                    negative_prompt=_NEGATIVE_PROMPT,
                                )
                            finally:
                                self._model_lock.release()
                            # Native inference belongs to this worker until it returns.
                            if monotonic() >= deadline:
                                raise TimeoutError()
                            return url if result["is_important"] else None
                    except TimeoutError:
                        logger.warning("%s_timeout phase=filter threshold_seconds=%s", event_prefix, self.image_seconds)
                        return None
                    except (aiohttp.ClientError, OSError, ValueError, TypeError) as error:
                        logger.info("%s_failed exception_type=%s", event_prefix, type(error).__name__)
                        return None
                    finally:
                        if image is not None:
                            image.close()

            selected = await asyncio.gather(*(one(url) for url in urls))
            return [url for url in selected if url is not None]


@cache
def web_image_filter():
    return WebImageFilter(enabled=environment.IMAGE_FILTER, model_path=environment.CLIP_MODEL_PATH)
