# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify the request contract used to reconcile shared model anchors."""

from contextlib import asynccontextmanager
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "automation"))
import prepare_anchor_assets as anchors


class AnchorModelPreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_payload_for_existing_and_new_anchors(self):
        for capability, stored_type, limit, model_name in (
            ("llm", "llm", 4096, "deepseek-v4-flash"),
            ("vlm", "llm", 8192, "fixture-vlm"),
            ("embedding", "embedding", 1024, "BAAI/bge-m3"),
        ):
            for exists in (True, False):
                with self.subTest(capability=capability, exists=exists):
                    await self.check_model_payload(capability, stored_type, limit, model_name, exists)

    async def check_model_payload(self, capability, stored_type, limit, model_name, exists):
        configured = {"capability": capability, "model": model_name, "secret_env_key": "KEY",
                      "base_url": "https://fixture.test/v1", "max_tokens": limit, "dimension": limit}
        row = {"display_name": model_name, "model_type": stored_type, "model_id": 42}
        listings = [[row] if exists else [], [row]]
        get = AsyncMock(side_effect=[httpx.Response(200, json={"data": rows}) for rows in listings])
        post = AsyncMock(return_value=httpx.Response(200, json={}))

        @asynccontextmanager
        async def client(service, *, token, timeout):
            yield SimpleNamespace(get=get, post=post)

        actions = []
        with (
            patch.object(anchors, "load_yaml", return_value={"models": [configured]}),
            patch.object(anchors, "load_secret_env", return_value={"KEY": "fixture-key"}),
            patch.object(anchors, "client", client),
        ):
            result = await anchors._ensure_models(SimpleNamespace(access_token="fixture-token"), actions)

        self.assertEqual(result, {f"primary_{capability}_id": 42})
        self.assertEqual(get.await_count, 2)
        self.assertEqual(post.await_count, 1)
        self.assertEqual(post.await_args.args, ("/model/update" if exists else "/model/create",))
        self.assertEqual(actions[0]["action"], "UPDATED" if exists else "CREATED")
        payload = post.await_args.kwargs["json"]
        self.assertEqual(payload["api_key"], "fixture-key")
        if exists and stored_type == "llm":
            self.assertNotIn("max_tokens", payload)
            self.assertNotIn("max_output_tokens", payload)
        else:
            self.assertEqual(payload["max_tokens"], limit)
        if capability == "embedding":
            self.assertEqual(payload["expected_chunk_size"], limit)
            self.assertEqual(payload["model_name"], "bge-m3" if exists else model_name)
            if exists:
                self.assertEqual(payload["model_repo"], "BAAI")
