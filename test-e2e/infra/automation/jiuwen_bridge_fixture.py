"""Controlled real HTTP/SSE fixtures for Jiuwen model bridge runtime cases."""

import asyncio
import json
from contextlib import asynccontextmanager

from nexent.core.model_service.profiles.composition import compose_provider_model_policy
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.outlet_resolution import construct_resolved_model_profile
from nexent.core.model_service.profiles.resolved_profile import ConnectionRules, ContextConfiguration, OutletConnection
from nexent.core.model_service.profiles.resolver import load_profile_catalog
from nexent.core.model_service.registry import model_service_references


def profile_for(url, protocol):
    """Construct a real resolved profile using the upstream public catalog."""
    registry = dict(model_service_references())
    catalog = load_profile_catalog()
    bindings = {key: registry[key][0].model_dump() for key in (
        "protocol", "auth", "adapter", "code_converter", "native_converter",
    )}
    policy = compose_provider_model_policy(
        catalog, provider_key="alibaba-cn", request_model_id="qwen3.5-plus", model_profile_key=None,
        base_bindings=bindings, base_instruction=VersionedReference(ref="system_only_v1", version=1),
        registered_references=registry, submitted_values={"enable_thinking": False},
    )
    profile = construct_resolved_model_profile(
        policy, catalog, tenant_id="spike-tenant", display_name="spike-outlet", model_type="llm",
        provider_id="alibaba", connection=OutletConnection(
            base_url=url + "/v1", ssl_verify=True, timeout_seconds=5, concurrency_limit=None,
            credential_ref={"kind": "model_record", "model_id": None},
        ), connection_rules=ConnectionRules(
            credential_kind="model_record", relative_path="/chat/completions", method="POST", headers={},
        ), context_configuration=ContextConfiguration(
            output_reserve_tokens=None, tokenizer_family=None, capacity_source="profile",
            capability_profile_version=None,
        ), registered_references=registry,
    )
    data = profile.model_dump()
    data["outlet_id"] = 7
    data["connection"]["credential_ref"]["model_id"] = 7
    if protocol != "native":
        data["capabilities"]["tools"]["status"] = "unsupported" if protocol == "text" else "unknown"
    return type(profile).model_validate(data)


@asynccontextmanager
async def provider(scenario, protocol):
    """Real local HTTP/SSE, single event loop, no external credentials or threads."""
    state = {"requests": [], "server_errors": [], "first_fragment_no_tool": None, "tool_calls": []}

    async def handle(reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            size = int(next(line.split(b":", 1)[1] for line in headers.split(b"\r\n")
                            if line.lower().startswith(b"content-length:")))
            body = json.loads(await reader.readexactly(size))
            state["requests"].append(body)
            first = (len(state["requests"]) == 1 or scenario == "bad_args"
                     or (scenario == "transient" and len(state["requests"]) == 2))
            if (scenario == "unavailable" or scenario == "transient" and len(state["requests"]) == 1
                    or scenario == "transient_after_tool" and len(state["requests"]) == 2):
                writer.write(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                await writer.drain()
                return
            if scenario == "auth":
                payload = json.dumps({"error": {"message": "fixture authentication failure", "type": "auth"}}).encode()
                writer.write(b"HTTP/1.1 401 Unauthorized\r\nContent-Type: application/json\r\nContent-Length: "
                             + str(len(payload)).encode() + b"\r\nConnection: close\r\n\r\n" + payload)
                await writer.drain()
                return
            call = {"id": "provider-call-1", "type": "function", "function": {
                "name": "add", "arguments": '{"a":2,"b":3}' if scenario != "bad_args" else '{"a":',
            }}
            if scenario == "cancel":
                content, calls = "PARTIAL_BEFORE_CANCEL", []
            elif scenario == "plain":
                content, calls = "Example only: ```python\nadd(2, 3)\n```", []
            elif protocol != "native" and first:
                content = "<code>\nresult = add(a=2, b=3)\nprint(result)\n</code>"
                if scenario == "truncated":
                    content = "<code>\nadd(a=2, b=3)"
                elif scenario == "ambiguous":
                    content += "\n<code>add(a=2,b=3)"
                calls = []
            elif protocol == "native" and first:
                content, calls = "", [call]
            else:
                content, calls = "SPIKE_FINAL_RESULT_5", []
            finish = "tool_calls" if calls else "stop"
            if scenario == "unknown_finish":
                finish = "mystery_control"
            if body.get("stream"):
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n")
                async def frame(delta, finish_reason=None):
                    value = {"id": "fixture-response", "object": "chat.completion.chunk", "model": body["model"],
                             "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}]}
                    if scenario == "duplicate_usage" and finish_reason:
                        value["usage"] = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
                    writer.write(("data: " + json.dumps(value) + "\n\n").encode())
                    await writer.drain()
                if calls:
                    await frame({"tool_calls": [{"index": 0, "id": call["id"], "type": "function", "function": {
                        "name": "add", "arguments": '{"a":',
                    }}]})
                    await asyncio.sleep(0.02)
                    state["first_fragment_no_tool"] = not state["tool_calls"]
                    if scenario == "broken_stream":
                        return
                    await frame({"tool_calls": [{"index": 0, "function": {
                        "arguments": '2,"b":3}' if scenario != "bad_args" else "",
                    }}]})
                else:
                    half = len(content) // 2
                    await frame({"content": content[:half]})
                    await asyncio.sleep(0.02)
                    state["first_fragment_no_tool"] = not state["tool_calls"] if first else state["first_fragment_no_tool"]
                    if scenario == "broken_stream":
                        return
                    if scenario == "cancel":
                        await reader.read()
                        state["cancel_response_closed"] = True
                        return
                    await frame({"content": content[half:]})
                await frame({}, finish)
                if scenario == "duplicate_usage":
                    value = {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}
                    writer.write(("data: " + json.dumps(value) + "\n\n").encode())
                writer.write(b"data: [DONE]\n\n")
                await writer.drain()
            else:
                payload = json.dumps({"id": "fixture-response", "object": "chat.completion", "model": body["model"],
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": content,
                                                          "tool_calls": calls}, "finish_reason": finish}]}).encode()
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                             + str(len(payload)).encode() + b"\r\nConnection: close\r\n\r\n" + payload)
                await writer.drain()
        except Exception as exc:
            state["server_errors"].append(type(exc).__name__)
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    async with server:
        yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}", state
