# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Cancellation joins the owned finalizer while retaining the cancellation outcome."""

import asyncio

import pytest

from management.services.agent.background import settle_background_projection


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_cancellation_waits_for_finalizer_and_does_not_mask_cancellation(fails):
    entered = asyncio.Event()
    release = asyncio.Event()
    settled = asyncio.Event()

    async def projection():
        entered.set()
        try:
            await release.wait()
            if fails:
                raise RuntimeError("controlled finalizer failure")
            return "committed"
        finally:
            settled.set()

    worker = asyncio.create_task(settle_background_projection(projection()))
    await entered.wait()
    worker.cancel()
    await asyncio.sleep(0)
    assert not worker.done() and not settled.is_set()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await worker
    assert settled.is_set()


@pytest.mark.asyncio
async def test_projection_success_and_failure_are_observed():
    async def success():
        return "committed"

    async def failure():
        raise RuntimeError("controlled finalizer failure")

    assert await settle_background_projection(success()) == "committed"
    with pytest.raises(RuntimeError, match="controlled"):
        await settle_background_projection(failure())
