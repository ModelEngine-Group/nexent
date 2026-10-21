"""MiniMax reasoning/tool history at the actual OpenAI HTTP boundary."""
import copy
import json
from unittest.mock import MagicMock

import httpx
import pytest

from nexent.core.models.openai_llm import OpenAIModel, _MiniMaxChatMessage


@pytest.mark.parametrize("history_format", ["object", "dict", "json"])
@pytest.mark.parametrize("model_id", ["MiniMax-M3.1-Flash", "MiniMax-M3", "MiniMax-M2.7", "team/custom-text"])
def test_parsed_tool_arguments_are_json_strings(model_id, history_format):
    captured = []

    def handle(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0, "model": model_id,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    model = OpenAIModel(model_id=model_id, api_base="https://api.minimax.io/v1", api_key="test-only",
                        model_factory="minimax", observer=MagicMock(),
                        client_kwargs={"http_client": httpx.Client(transport=httpx.MockTransport(handle))})
    original_string = '{ "q" : "keep whitespace" }'
    assistant = _MiniMaxChatMessage.from_dict({
        "role": "assistant", "content": "checking two sources",
        "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "lookup", "arguments": '{"q":"中文","nested":{"ok":true},"items":[1,null]}'}},
            {"id": "b", "type": "function", "function": {"name": "lookup", "arguments": original_string}},
        ],
    })
    assistant.reasoning_content = "compare both results"
    model.parse_tool_calls(assistant)
    parsed = copy.deepcopy(assistant.tool_calls[0].function.arguments)
    assert isinstance(parsed, dict)
    # A mixed history must not re-encode already serialized arguments.
    assistant.tool_calls[1].function.arguments = original_string
    before = assistant.model_dump_json()
    history_message = assistant
    if history_format == "dict":
        history_message = assistant.dict()
    elif history_format == "json":
        history_message = json.loads(before)
    history_before = copy.deepcopy(history_message)
    try:
        model.generate([
            {"role": "user", "content": "compare"}, history_message,
            {"role": "tool", "tool_call_id": "a", "content": "first"},
            {"role": "tool", "tool_call_id": "b", "content": "second"},
            {"role": "assistant", "content": "ready", "reasoning_content": "checked"},
            {"role": "user", "content": "continue"},
        ])
        wire = captured[-1]
        assert wire["model"] == model_id
        calls = wire["messages"][1]["tool_calls"]
        assert isinstance(calls[0]["function"]["arguments"], str)
        assert json.loads(calls[0]["function"]["arguments"]) == parsed
        assert calls[1]["function"]["arguments"] == original_string
        assert wire["messages"][1]["reasoning_content"] == "compare both results"
        assert wire["messages"][2]["tool_call_id"] == "a"
        assert wire["messages"][3]["tool_call_id"] == "b"
        assert wire["messages"][4]["reasoning_content"] == "checked"
        assert history_message == history_before
        assert assistant.model_dump_json() == before
    finally:
        model.client.close()


@pytest.mark.parametrize("stream", [False, True])
def test_assistant_reasoning_survives_text_history(stream):
    captured = []

    def handle(request):
        captured.append(json.loads(request.content))
        if captured[-1].get("stream"):
            chunk = {"id": "t", "object": "chat.completion.chunk", "created": 0, "model": "MiniMax-M3.1-Flash",
                     "choices": [{"index": 0, "delta": {"content": "ok", "reasoning_content": "new thought"}}],
                     "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"},
                                  content="data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n")
        return httpx.Response(200, json={"id": "t", "object": "chat.completion", "created": 0, "model": "MiniMax-M3.1-Flash",
                                       "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok", "reasoning_content": "new thought"}, "finish_reason": "stop"}],
                                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

    model = OpenAIModel(model_id="MiniMax-M3.1-Flash", api_base="https://api.minimax.io/v1", api_key="test-only",
                        model_factory="minimax", observer=MagicMock(),
                        client_kwargs={"http_client": httpx.Client(transport=httpx.MockTransport(handle))})
    try:
        history = [{"role": "user", "content": "question"},
                   {"role": "assistant", "content": "answer", "reasoning_content": "original thought"},
                   {"role": "user", "content": "next"}]
        result = (model if stream else model.generate)(history)
        assert captured[-1]["messages"][1]["reasoning_content"] == "original thought"
        assert result.reasoning_content == "new thought"
    finally:
        model.client.close()


@pytest.mark.parametrize("model_id", ["MiniMax-M3.1-Flash", "MiniMax-M3", "MiniMax-M2.7", "team/custom-text"])
@pytest.mark.parametrize("stream", [False, True])
def test_reasoning_and_tools_round_trip(model_id, stream):
    captured = []
    tool_call = {"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": '{"q":"x"}'}}

    def handle(request):
        captured.append(json.loads(request.content))
        response = {"id": "test", "object": "chat.completion", "created": 0, "model": model_id,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "answer", "reasoning_content": "think more", "tool_calls": [tool_call]}, "finish_reason": "tool_calls"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        if not captured[-1].get("stream"):
            return httpx.Response(200, json=response)
        deltas = [
            {"role": "assistant", "reasoning_content": "think ", "content": "an"},
            {"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": '{"q":'}}]},
            {"content": "swer", "reasoning_content": "more", "tool_calls": [{"index": 0, "function": {"arguments": '"x"}'}}]},
        ]
        chunks = [{"id": "test", "object": "chat.completion.chunk", "created": 0, "model": model_id,
                   "choices": [{"index": 0, "delta": delta, "finish_reason": None}]} for delta in deltas]
        chunks.append({"id": "test", "object": "chat.completion.chunk", "created": 0, "model": model_id,
                       "choices": [], "usage": response["usage"]})
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"},
                              content="".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n")

    client = httpx.Client(transport=httpx.MockTransport(handle))
    model = OpenAIModel(model_id=model_id, api_base="https://api.minimax.io/v1", api_key="test-only",
                        model_factory="minimax", observer=MagicMock(), client_kwargs={"http_client": client})
    history = [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": None, "reasoning_content": "first", "tool_calls": [tool_call]},
        {"role": "tool", "content": "result", "tool_call_id": "call_1"},
        {"role": "assistant", "content": "continue", "reasoning_content": "second"},
        {"role": "assistant", "content": "another", "reasoning_content": "third"},
        {"role": "user", "content": [{"type": "text", "text": "next"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}]},
    ]
    original = copy.deepcopy(history)
    invoke = model if stream else model.generate
    try:
        result = invoke(history)
        assert captured[-1]["messages"] == original
        assert captured[-1]["model"] == model_id
        assert history == original
        assert result.content == "answer"
        assert result.reasoning_content == "think more"
        serialized = json.loads(result.model_dump_json())
        assert serialized["reasoning_content"] == "think more"
        assert serialized["tool_calls"][0]["id"] == "call_1"
        # Returned object, then serialized history, must both survive a next turn.
        for assistant in [result, serialized]:
            invoke([{"role": "user", "content": "question"}, assistant,
                    {"role": "tool", "content": "done", "tool_call_id": "call_1"}])
            outgoing = captured[-1]["messages"]
            assert outgoing[1]["reasoning_content"] == "think more"
            assert outgoing[1]["tool_calls"] == [tool_call]
            assert outgoing[2]["tool_call_id"] == "call_1"
        if stream:
            model.observer.add_model_reasoning_content.assert_any_call("think ")
            model.observer.add_model_reasoning_content.assert_any_call("more")
    finally:
        model.client.close()
