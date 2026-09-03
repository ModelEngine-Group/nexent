#!/usr/bin/env python3
"""HTTP E2E evidence server for runtime-memory acceptance scenarios."""

import asyncio
import gc
import hashlib
import os
import resource
import sys
import time

sys.path.insert(0, "/opt/backend")

import services.streaming_channel as streaming_module
from agents.agent_run_manager import agent_run_manager
from fastapi import FastAPI
from management.services.agent.service import (
    _agent_stream_producer_tasks,
    _finalize_buffered_unit_fragments,
)
from services.streaming_channel import StreamingChannel, StreamingChannelManager

app = FastAPI()


async def _no_runtime_write(**_kwargs):
    return None


streaming_module.runtime_state_service.append_stream_event_async = _no_runtime_write
streaming_module.runtime_state_service.mark_stream_completed_async = _no_runtime_write


def _rss_bytes() -> int:
    with open("/proc/self/status", encoding="utf-8") as status_file:
        for line in status_file:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    raise RuntimeError("VmRSS unavailable")


@app.post("/e2e/replay")
async def replay_scenario():
    channel = StreamingChannel("e2e-replay", "e2e", history_size=10_000)
    expected = []
    for index in range(512):
        chunk = ("x" * (64 * 1024 - 8)) + f"{index:08d}"
        expected.append(chunk)
        await channel.publish(chunk)
    channel.complete()
    replayed = [chunk async for chunk in channel.subscribe_with_history(channel.history_start_index)]
    retained_expected = expected[-len(replayed):]
    return {
        "scenario": "E2E-01 bounded HTTP replay",
        "result": "PASS" if replayed == retained_expected else "FAIL",
        "published_events": len(expected),
        "replayed_events": len(replayed),
        "retained_bytes": channel.history_bytes,
        "byte_limit": channel._history_max_bytes,
        "absolute_start_index": channel.history_start_index,
        "ordered_duplicate_free": replayed == retained_expected,
    }


@app.post("/e2e/disconnect")
async def disconnect_scenario():
    manager = StreamingChannelManager()
    channel = await manager.get_or_create_channel(900001, "e2e-disconnect", history_size=200)
    produced = 0

    async def producer():
        nonlocal produced
        for index in range(50):
            await channel.publish(f"event-{index}")
            produced += 1
            await asyncio.sleep(0.002)
        channel.complete()

    task = asyncio.create_task(producer())
    _agent_stream_producer_tasks.add(task)
    task.add_done_callback(_agent_stream_producer_tasks.discard)
    subscription = channel.subscribe()
    first = await anext(subscription)
    await subscription.aclose()
    await task
    await manager.remove_channel(900001, "e2e-disconnect", expected_channel=channel)
    await asyncio.sleep(0)
    clean = manager.get_active_channel_count() == 0 and len(_agent_stream_producer_tasks) == 0
    return {
        "scenario": "E2E-02 disconnect continuation and cleanup",
        "result": "PASS" if first == "event-0" and produced == 50 and clean else "FAIL",
        "first_event": first,
        "produced_after_disconnect": produced,
        "active_channels": manager.get_active_channel_count(),
        "active_producers": len(_agent_stream_producer_tasks),
        "active_runs": agent_run_manager.get_active_run_count(),
    }


@app.post("/e2e/persistence")
async def persistence_scenario():
    fragments = [f"{index:08d}" + "y" * (4096 - 8) for index in range(8192)]
    expected_digest = hashlib.sha256("".join(fragments).encode()).hexdigest()
    units = [{
        "type": "model_output",
        "content": "",
        "unit_content": "",
        "_content_fragments": fragments,
    }]
    started = time.perf_counter()
    byte_count = _finalize_buffered_unit_fragments(units)
    elapsed = time.perf_counter() - started
    digest = hashlib.sha256(units[0]["content"].encode()).hexdigest()
    clean_schema = "_content_fragments" not in units[0]
    return {
        "scenario": "E2E-03 persistence finalization",
        "result": "PASS" if digest == expected_digest and clean_schema else "FAIL",
        "bytes": byte_count,
        "sha256_match": digest == expected_digest,
        "private_fragments_removed": clean_schema,
        "finalization_seconds": elapsed,
    }


@app.post("/e2e/waves")
async def waves_scenario():
    baseline = _rss_bytes()
    waves = []
    for wave in range(1, 4):
        channels = [StreamingChannel(str(i), "waves", history_size=10_000) for i in range(20)]
        for chunk_index in range(1024):
            # Keep one distinct object per channel so RSS reflects the full
            # retained payload instead of sharing a single Python string.
            await asyncio.gather(*(
                channel.publish(
                    ("z" * (64 * 1024 - 16)) + f"{channel_index:08d}{chunk_index:08d}"
                )
                for channel_index, channel in enumerate(channels)
            ))
        retained = sum(channel.history_bytes for channel in channels)
        peak = _rss_bytes()
        channels.clear()
        gc.collect()
        waves.append({"wave": wave, "retained_bytes": retained, "peak_rss": peak, "quiescent_rss": _rss_bytes()})
    peaks = [wave["peak_rss"] for wave in waves]
    quiescent = [wave["quiescent_rss"] for wave in waves]
    stable = max(peaks) - min(peaks) <= max(int(max(peaks) * 0.1), 64 * 1024 * 1024)
    stable = stable and max(quiescent) - min(quiescent) <= max(int(max(quiescent) * 0.1), 64 * 1024 * 1024)
    under_limit = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 < 1200 * 1024 * 1024
    return {
        "scenario": "E2E-04 repeated memory waves",
        "result": "PASS" if stable and under_limit else "FAIL",
        "baseline_rss": baseline,
        "process_peak_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "stable": stable,
        "under_1_2_gib": under_limit,
        "waves": waves,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "pid": os.getpid()}
