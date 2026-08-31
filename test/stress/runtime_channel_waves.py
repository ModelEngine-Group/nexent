#!/usr/bin/env python3
"""Run repeated deterministic waves against the production StreamingChannel."""

import argparse
import asyncio
import gc
import json
import os
import resource
import sys

sys.path.insert(0, "/opt/backend")

from services.streaming_channel import StreamingChannel  # noqa: E402
import services.streaming_channel as streaming_module  # noqa: E402


def rss_bytes() -> int:
    with open("/proc/self/status", encoding="utf-8") as status_file:
        for line in status_file:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    raise RuntimeError("VmRSS unavailable")


async def no_runtime_write(**_kwargs):
    return None


async def run_wave(concurrency: int, payload_mib: int, chunk_kib: int) -> dict:
    channels = [StreamingChannel(str(i), "pressure", history_size=10_000) for i in range(concurrency)]
    chunks_per_channel = payload_mib * 1024 // chunk_kib

    async def produce(channel: StreamingChannel, channel_index: int) -> None:
        for chunk_index in range(chunks_per_channel):
            content = (
                "x" * max(0, chunk_kib * 1024 - 32)
                + f"-{channel_index:015d}-{chunk_index:015d}"
            )
            await channel.publish(content)
        channel.complete()

    await asyncio.gather(*(
        produce(channel, channel_index)
        for channel_index, channel in enumerate(channels)
    ))
    retained_bytes = sum(channel.history_bytes for channel in channels)
    retained_events = sum(channel.history_size for channel in channels)
    result = {
        "retained_bytes": retained_bytes,
        "retained_events": retained_events,
        "rss_at_peak_bytes": rss_bytes(),
    }
    channels.clear()
    gc.collect()
    result["rss_after_gc_bytes"] = rss_bytes()
    return result


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--waves", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--payload-mib", type=int, default=64)
    parser.add_argument("--chunk-kib", type=int, default=64)
    args = parser.parse_args()
    streaming_module.runtime_state_service.append_stream_event_async = no_runtime_write
    baseline = rss_bytes()
    results = []
    for wave in range(1, args.waves + 1):
        result = await run_wave(args.concurrency, args.payload_mib, args.chunk_kib)
        result["wave"] = wave
        results.append(result)
    print(json.dumps({
        "baseline_rss_bytes": baseline,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "parameters": vars(args),
        "waves": results,
        "pid": os.getpid(),
    }, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
