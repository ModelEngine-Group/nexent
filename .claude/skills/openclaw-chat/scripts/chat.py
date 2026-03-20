#!/usr/bin/env python3
"""OpenClaw WebSocket Chat Client.

Send messages to OpenClaw service via WebSocket and return responses.
"""

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

import websockets
import yaml


def load_config(config_path: str | None = None) -> dict:
    """Load configuration from YAML file."""
    if config_path is None:
        config_path = str(Path(__file__).parent.parent / "config" / "config.yaml")

    with open(config_path, "r") as f:
        return yaml.safe_load(f) or {}


async def send_message(
    host: str,
    port: str,
    token: str,
    message: str,
) -> str | None:
    """Send message to OpenClaw and return final response text."""
    ws_url = f"ws://{host}:{port}/"
    origin = f"http://{host}:{port}"

    try:
        async with websockets.connect(
            ws_url, additional_headers={"Origin": origin}
        ) as websocket:
            await websocket.recv()

            token_data = {
                "type": "req",
                "id": str(uuid.uuid4()),
                "method": "connect",
                "params": {
                    "minProtocol": 3,
                    "maxProtocol": 3,
                    "client": {
                        "id": "openclaw-control-ui",
                        "version": "3.10",
                        "platform": "python",
                        "mode": "webchat",
                    },
                    "caps": ["tool-events"],
                    "role": "operator",
                    "scopes": [
                        "operator.approvals",
                        "operator.pairing",
                        "operator.admin",
                        "operator.write",
                    ],
                    "auth": {"token": token},
                    "locale": "zh-CN",
                    "userAgent": "gateway-client",
                },
            }

            await websocket.send(json.dumps(token_data))
            await websocket.recv()

            request_data = {
                "type": "req",
                "params": {
                    "deliver": False,
                    "idempotencyKey": str(uuid.uuid4()),
                    "message": message,
                    "sessionKey": "agent:operator_main:main",
                },
                "method": "chat.send",
                "id": str(uuid.uuid4()),
            }

            await websocket.send(json.dumps(request_data))

            while True:
                response = await websocket.recv()
                data = json.loads(response)

                if (
                    data.get("type") == "event"
                    and data.get("event") == "chat"
                    and data.get("payload", {}).get("state") == "final"
                ):
                    payload = data.get("payload", {})
                    msg = payload.get("message", {})
                    content_list = msg.get("content", [])

                    texts = []
                    for content in content_list:
                        if content.get("type") == "text":
                            texts.append(content.get("text", ""))

                    return "\n".join(texts) if texts else None

    except websockets.exceptions.ConnectionClosed as e:
        print(f"Connection closed: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return None


async def main_async(args: argparse.Namespace) -> None:
    """Main async entry point."""
    config = load_config(args.config)

    host = args.host or config.get("host", "localhost")
    port = args.port or config.get("port", "18789")
    token = args.token or config.get("token", "")

    result = await send_message(host, port, token, args.message)

    if result:
        print(result)
    else:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="OpenClaw WebSocket Chat Client",
        epilog="Example: python chat.py --message 'List available skills'",
    )
    parser.add_argument("--host", help="WebSocket server host")
    parser.add_argument("--port", help="WebSocket server port")
    parser.add_argument("--token", help="Auth token")
    parser.add_argument(
        "--config",
        help="Path to config YAML file (default: ../config/config.yaml)",
    )
    parser.add_argument(
        "--message",
        required=True,
        help="Chat message to send",
    )
    args = parser.parse_args()

    asyncio.run(main_async(args))
