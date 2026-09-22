#!/usr/bin/env python3
"""Small dependency-free probe for Agent Card discovery and JSON-RPC invocation."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid


def request_json(url: str, headers: dict[str, str], payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="GET" if data is None else "POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe an A2A Agent Card and optionally invoke SendMessage.")
    parser.add_argument("card_url")
    parser.add_argument("--header", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--message", default="Query pedestrian flow")
    parser.add_argument("--discover-only", action="store_true")
    args = parser.parse_args()
    headers = {"Accept": "application/json"}
    for item in args.header:
        name, separator, value = item.partition("=")
        if not separator:
            parser.error(f"Invalid header assignment: {item}")
        headers[name] = value
    try:
        card = request_json(args.card_url, headers)
        print(json.dumps({"card": card}, ensure_ascii=False, indent=2))
        if args.discover_only:
            return 0
        interfaces = card.get("supportedInterfaces") or []
        jsonrpc = next((item for item in interfaces if item.get("protocolBinding") == "JSONRPC"), None)
        if not jsonrpc:
            raise RuntimeError("Agent Card does not advertise a JSONRPC interface")
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": str(uuid.uuid4()),
                    "role": "ROLE_USER",
                    "parts": [{"text": args.message}],
                }
            },
        }
        response = request_json(
            jsonrpc["url"],
            {
                **headers,
                "Content-Type": "application/json",
                "A2A-Version": ".".join(str(jsonrpc.get("protocolVersion", "1.0")).split(".")[:2]),
            },
            payload,
        )
        print(json.dumps({"response": response}, ensure_ascii=False, indent=2))
        if response.get("error") or not response.get("result"):
            raise RuntimeError("A2A invocation returned an error or no result")
        return 0
    except (urllib.error.URLError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"A2A probe failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
