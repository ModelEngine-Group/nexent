# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import sys
from pathlib import Path

import docker
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "sdk"), str(ROOT), str(Path(__file__).parent)]
from build_fixtures import build_images


@pytest.mark.case_id("EVOLUTION-TOOL-BUILD-D3-001")
@pytest.mark.stage("D3")
def test_reviewed_builds():
    from management.cli.verify_tool_build import _observe, compare
    from nexent.core.agents.resources.replay_tools import argument_digest

    client = docker.from_env()
    try:
        images = build_images(client)
        manifest = {"port": 8000, "path": "/mcp", "transport": "streamable-http"}
        for reference, label in [("Q61", "failure"), ("R84", "caller/return")]:
            rule = {
                "name": "post_delivery_receipt",
                "min_calls": 1,
                "max_calls": 1,
                "arguments": {"reference": reference},
                "expected_mcp_reply": {
                    "kind": "text",
                    "value": "LEDGER_ACK",
                    "fixture": {"initial": {"receipt": ""}, "final": {"receipt": reference}},
                },
            }
            old = _observe(client, images["verifier"], images["base"], manifest, rule)
            new = _observe(client, images["verifier"], images["corrected"], manifest, rule)
            original = old["observation"]
            assert original["before"] == argument_digest({"receipt": ""})
            assert original["after"] == argument_digest(
                {"receipt": reference.lower() if label == "failure" else reference}
            )
            check = {
                "label": label,
                "original": {
                    k: original[k] for k in ("remote", "kind", "inputs", "content", "before", "after", "error")
                },
            }
            assert compare(check, old, new) == ("corrected" if label == "failure" else "protected")
            assert new["observation"]["after"] == argument_digest({"receipt": reference})
            assert reference not in str(new)
            if label == "failure":
                assert compare(check, new, new) == "baseline_mismatch"
            else:
                bad = _observe(client, images["verifier"], images["regressed"], manifest, rule)
                assert compare(check, old, bad) == "regression"
    finally:
        client.close()
