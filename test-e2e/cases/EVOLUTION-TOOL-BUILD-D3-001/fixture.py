# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Synthetic service with an independently readable delivery ledger."""

import json
import os

from mcp.server.fastmcp import FastMCP

service = FastMCP("pilot-ledger", host="127.0.0.1", port=8000, stateless_http=True, json_response=True)
ledger = json.loads(os.environ["NEXENT_EVAL_FIXTURE_INITIAL"])


@service.resource("nexent-eval://fixture/state")
def state() -> str:
    return json.dumps(ledger)


@service.tool()
def post_delivery_receipt(reference: str) -> str:
    """Enter the delivery reference into the test ledger."""
    ledger["receipt"] = entry(reference)
    return "LEDGER_ACK"


from fixture_entry import entry

if __name__ == "__main__":
    service.run(transport="streamable-http")
