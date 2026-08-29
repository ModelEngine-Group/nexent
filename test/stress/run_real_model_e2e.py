#!/usr/bin/env python3
"""Run secret-safe one-user and five-user real-model verification."""

import json
from concurrent.futures import ThreadPoolExecutor

from real_model_probe import run_probe


def passed(results: list[dict]) -> bool:
    return all(item.get("marker_present") for item in results)


def main() -> int:
    single = [run_probe()]
    with ThreadPoolExecutor(max_workers=5) as executor:
        concurrent = list(executor.map(lambda _index: run_probe(), range(5)))
    result = {
        "scenario": "E2E-05 real model 1/5-user verification",
        "result": "PASS" if passed(single) and passed(concurrent) else "FAIL",
        "single_user": single,
        "five_users": concurrent,
        "single_successes": sum(item["marker_present"] for item in single),
        "concurrent_successes": sum(item["marker_present"] for item in concurrent),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
