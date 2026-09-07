#!/usr/bin/env python3
"""Fresh-process A/B probes for the two proven runtime memory amplifiers.

This intentionally has no Nexent or third-party imports so it can run in a
newly provisioned VM before the application dependency set is installed.
"""

import argparse
from collections import deque
import json
import os
import resource
import time


def current_rss_bytes() -> int:
    with open("/proc/self/status", encoding="utf-8") as status_file:
        for line in status_file:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    raise RuntimeError("VmRSS is unavailable")


def run_history(payload_mib: int, chunk_kib: int, bounded: bool) -> dict:
    payload_bytes = payload_mib * 1024 * 1024
    chunk_bytes = chunk_kib * 1024
    chunks = (payload_bytes + chunk_bytes - 1) // chunk_bytes
    retained = deque()
    retained_bytes = 0
    rss_before = current_rss_bytes()
    started = time.perf_counter()
    for index in range(chunks):
        chunk = ("x" * max(0, chunk_bytes - 16)) + f"-{index:015d}"
        encoded_bytes = len(chunk.encode("utf-8"))
        retained.append((chunk, encoded_bytes))
        retained_bytes += encoded_bytes
        if bounded:
            while retained_bytes > 8 * 1024 * 1024 and len(retained) > 1:
                _, removed_bytes = retained.popleft()
                retained_bytes -= removed_bytes
    return {
        "scenario": "history-bounded" if bounded else "history-unbounded",
        "payload_bytes": payload_bytes,
        "retained_bytes": retained_bytes,
        "retained_events": len(retained),
        "rss_delta_bytes": current_rss_bytes() - rss_before,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "elapsed_seconds": time.perf_counter() - started,
    }


def run_persistence(payload_mib: int, chunk_kib: int, fragments: bool) -> dict:
    payload_bytes = payload_mib * 1024 * 1024
    chunk_bytes = chunk_kib * 1024
    chunks = (payload_bytes + chunk_bytes - 1) // chunk_bytes
    rss_before = current_rss_bytes()
    started = time.perf_counter()
    if fragments:
        buffered = []
        for index in range(chunks):
            buffered.append(("y" * max(0, chunk_bytes - 16)) + f"-{index:015d}")
        content = "".join(buffered)
    else:
        # Match production's dictionary-held growing string. The extra owning
        # reference prevents CPython's local-variable concat fast path.
        unit = {"content": ""}
        for index in range(chunks):
            unit["content"] += ("y" * max(0, chunk_bytes - 16)) + f"-{index:015d}"
        content = unit["content"]
    return {
        "scenario": "persistence-fragments" if fragments else "persistence-concat",
        "payload_bytes": payload_bytes,
        "final_bytes": len(content.encode("utf-8")),
        "rss_delta_bytes": current_rss_bytes() - rss_before,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "elapsed_seconds": time.perf_counter() - started,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=(
        "history-unbounded", "history-bounded",
        "persistence-concat", "persistence-fragments",
    ))
    parser.add_argument("--payload-mib", type=int, required=True)
    parser.add_argument("--chunk-kib", type=int, default=64)
    args = parser.parse_args()
    if args.payload_mib < 1 or args.chunk_kib < 1:
        parser.error("payload and chunk sizes must be positive")
    if args.scenario.startswith("history"):
        result = run_history(
            args.payload_mib, args.chunk_kib,
            bounded=args.scenario == "history-bounded",
        )
    else:
        result = run_persistence(
            args.payload_mib, args.chunk_kib,
            fragments=args.scenario == "persistence-fragments",
        )
    result.update({"pid": os.getpid(), "chunk_kib": args.chunk_kib})
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
