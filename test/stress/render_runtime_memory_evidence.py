#!/usr/bin/env python3
"""Run scoped HTTP E2E scenarios and render reviewable evidence pages."""

import argparse
import datetime as dt
import html
import json
import urllib.request
from pathlib import Path

SCENARIOS = (
    ("E2E-01", "有界本地重放与游标顺序", "/e2e/replay"),
    ("E2E-02", "客户端断连后继续执行与资源清理", "/e2e/disconnect"),
    ("E2E-03", "持久化片段一次性合并", "/e2e/persistence"),
    ("E2E-04", "三轮内存压力稳定性", "/e2e/waves"),
)


def post_json(url: str) -> dict:
    request = urllib.request.Request(url, data=b"", method="POST")
    with urllib.request.urlopen(request, timeout=900) as response:
        return json.load(response)


def render_page(test_id: str, title: str, result: dict, timestamp: str) -> str:
    status = result.get("result", "UNKNOWN")
    status_class = "pass" if status == "PASS" else "fail"
    rows = []
    for key, value in result.items():
        if key in {"scenario", "result"}:
            continue
        if key == "waves":
            for wave in value:
                wave_number = wave.get("wave", "?")
                wave_value = ", ".join(f"{item_key}={item_value}" for item_key, item_value in wave.items())
                rows.append(
                    f"<tr><th>wave_{wave_number}</th><td>{html.escape(wave_value)}</td></tr>"
                )
            continue
        display = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        rows.append(f"<tr><th>{html.escape(key)}</th><td>{html.escape(display)}</td></tr>")
    details = html.escape(json.dumps(result, ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{test_id} {html.escape(title)}</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;background:#f3f5f8;color:#172033;margin:0;padding:36px}}
.card{{max-width:1040px;margin:auto;background:white;border-radius:16px;padding:32px;box-shadow:0 8px 28px #1d2a3a18}}
.meta{{color:#687386;font-size:14px}} h1{{margin:8px 0 20px;font-size:30px}}
.badge{{display:inline-block;padding:8px 18px;border-radius:999px;font-weight:800}} .pass{{background:#d9f8e5;color:#087333}} .fail{{background:#ffe0e0;color:#ad1515}}
table{{border-collapse:collapse;width:100%;margin:24px 0}} th,td{{border-bottom:1px solid #e3e7ee;padding:12px;text-align:left}} th{{width:34%;color:#526074}}
details{{margin-top:20px}} pre{{background:#101827;color:#d9e2f2;padding:20px;border-radius:10px;white-space:pre-wrap;overflow-wrap:anywhere}}
</style></head><body><main class="card"><div class="meta">Nexent Runtime Memory Pressure · {test_id} · {timestamp}</div>
<h1>{html.escape(title)}</h1><span class="badge {status_class}">{html.escape(status)}</span>
<table>{''.join(rows)}</table><details><summary>原始结果 JSON</summary><pre>{details}</pre></details>
</main></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5088")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
    failed = False
    summary = []
    for test_id, title, endpoint in SCENARIOS:
        result = post_json(f"{args.base_url}{endpoint}")
        failed = failed or result.get("result") != "PASS"
        stem = test_id.lower()
        (output_dir / f"{stem}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (output_dir / f"{stem}.html").write_text(
            render_page(test_id, title, result, timestamp), encoding="utf-8"
        )
        summary.append({"test_id": test_id, "title": title, "result": result.get("result")})
        print(f"{test_id}: {result.get('result')}")
    (output_dir / "summary.json").write_text(
        json.dumps({"timestamp": timestamp, "tests": summary}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
