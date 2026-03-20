import asyncio
import uuid
import argparse

import websockets
import json


async def connect_and_request(host, port, token, message):
    ws_url = f"ws://{host}:{port}/"

    try:
        origin = f"http://{host}:{port}"
        async with websockets.connect(
            ws_url, additional_headers={"Origin": origin}
        ) as websocket:
            print("🌐 连接已建立")
            response = await websocket.recv()
            print(f"✅ 收到响应: {response}")

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
            print(f"📤 请求已下发: {token_data}")

            response = await websocket.recv()
            print(f"✅ 收到响应: {response}")

            # 准备请求数据
            run_id = str(uuid.uuid4())
            request_data = {
                "type": "req",
                "params": {
                    "deliver": False,
                    "idempotencyKey": run_id,
                    "message": message,
                    "sessionKey": "agent:operator_main:main",
                },
                "method": "chat.send",
                "id": str(uuid.uuid4()),
            }

            # 下发请求
            await websocket.send(json.dumps(request_data))
            print(f"📤 请求已下发: {request_data}")

            # 等待并接收响应，直到收到 final 状态
            while True:
                response = await websocket.recv()
                data = json.loads(response)
                print(f"✅ 收到响应: {data}")

                if (
                    data.get("type") == "event"
                    and data.get("event") == "chat"
                    and data.get("payload", {}).get("state") == "final"
                ):
                    payload = data.get("payload", {})
                    message = payload.get("message", {})
                    content_list = message.get("content", [])

                    for content in content_list:
                        if content.get("type") == "text":
                            print(f"📝 最终响应: {content.get('text')}")

                    break

    except websockets.exceptions.ConnectionClosed as e:
        print(f"🔌 连接已断开: {e}")
    except Exception as e:
        print(f"❌ 发生异常: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="WebSocket Chat Client",
        epilog="示例: python chat.py --message '安装deploy-to-vercel skill'",
    )
    parser.add_argument("--host", default="localhost", help="WebSocket server host")
    parser.add_argument("--port", default="18789", help="WebSocket server port")
    parser.add_argument(
        "--token",
        default="token",
        help="Auth token",
    )
    parser.add_argument(
        "--message",
        required=True,
        help="Chat message to send",
    )
    args = parser.parse_args()

    asyncio.run(connect_and_request(args.host, args.port, args.token, args.message))
