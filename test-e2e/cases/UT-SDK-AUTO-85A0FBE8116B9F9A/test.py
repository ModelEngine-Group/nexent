import threading
import types

import pytest

from nexent.core.agents.core_agent import CoreAgent
from nexent.core.context_runtime.contracts import FinalContext
from nexent.core.models import openai_llm
from nexent.core.models.context_overflow import (
    ProviderContextOverflowRetryExhausted,
    ProviderContextOverflowRetryUnsafe,
    is_provider_context_overflow,
)
from nexent.core.models.openai_llm import OpenAIModel
from nexent.core.model_errors import ModelErrorCode, ModelInvocationTerminalError


class _FakeProviderOverflow(Exception):
    code = 'context_length_exceeded'

    def __init__(self, message='maximum context length exceeded'):
        super().__init__(message)


class _FakeDelta:
    def __init__(self, content=None, role=None):
        self.content = content
        self.role = role
        self.reasoning = None
        self.reasoning_content = None


class _FakeChoice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class _FakeChunk:
    def __init__(self, content=None, role=None, finish_reason=None, usage=None):
        self.choices = [_FakeChoice(_FakeDelta(content, role), finish_reason)]
        self.usage = usage


class _FakeUsage:
    def __init__(self, prompt_tokens, completion_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens


def _success_stream():
    return [
        _FakeChunk(content='hello', role='assistant'),
        _FakeChunk(finish_reason='stop', usage=_FakeUsage(7, 5)),
    ]


class _FakeCompletions:
    def __init__(self, behaviors):
        self.behaviors = list(behaviors)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        behavior = self.behaviors.pop(0)
        if isinstance(behavior, BaseException):
            raise behavior
        return behavior


class _FakeClient:
    def __init__(self, behaviors):
        self.completions = _FakeCompletions(behaviors)
        self.chat = types.SimpleNamespace(completions=self.completions)


class _StubObserver:
    def __init__(self):
        self.current_mode = None
        self.tokens = []

    def add_model_new_token(self, token):
        self.tokens.append(token)

    def add_model_reasoning_content(self, content):
        pass

    def flush_remaining_tokens(self):
        pass


class _StubCancellationScope:
    def __init__(self):
        self.cancelled = False
        self.stop_event = threading.Event()

    def register_closer(self, closer):
        return None

    def unregister_closer(self, token):
        pass


class _StubTokenTracker:
    def record_first_token(self):
        pass

    def record_token(self, token):
        pass

    def record_completion(self, input_tokens, output_tokens):
        pass


class _StubMonitoring:
    def add_span_event(self, name, attributes=None):
        pass

    def set_span_attributes(self, **attrs):
        pass

    def set_openinference_output(self, value):
        pass

    def create_token_tracker(self, model_name, span=None):
        return _StubTokenTracker()


class _FakeRuntime:
    def __init__(self):
        self.recover_step_calls = 0
        self.recover_final_answer_calls = 0

    def recover_step(self, **kwargs):
        self.recover_step_calls += 1
        return FinalContext(messages=[{'role': 'user', 'content': 'rebuilt-step'}])

    def recover_final_answer(self, **kwargs):
        self.recover_final_answer_calls += 1
        return FinalContext(messages=[{'role': 'user', 'content': 'rebuilt-final'}])


class _FakePermit:
    def __init__(self, sink):
        self._sink = sink

    def release(self):
        self._sink.append('release')


class _FakeLimiter:
    def __init__(self):
        self.events = []

    def acquire(self, key, limit, timeout_seconds, stop_event):
        self.events.append('acquire')
        return _FakePermit(self.events)


def _build_model(client, concurrency_limit=None):
    model = object.__new__(OpenAIModel)
    model.observer = _StubObserver()
    model.temperature = 0.2
    model.top_p = 0.95
    model.stop_event = threading.Event()
    model.cancellation_scope = _StubCancellationScope()
    model.concurrency_limit = concurrency_limit
    model.concurrency_key = None
    model.concurrency_wait_timeout_seconds = 30.0
    model._monitoring = _StubMonitoring()
    model.model_factory = ''
    model.model_id = 'test-model'
    model.display_name = None
    model.flatten_messages_as_text = False
    model.extra_body = None
    model.prompt_cache = None
    model.reasoning_effort = None
    model.reasoning_budget_tokens = None
    model.reasoning_capability = None
    model._context_budget_snapshot = None
    model.capacity_snapshot = None
    model.max_output_tokens = None
    model.max_tokens = None
    model.last_response_diagnostics = None
    model.last_context_evidence = None
    model.last_finish_reason = None
    model.retry_config = types.SimpleNamespace(max_attempts=4, calculate_backoff=lambda attempt: 0.0)
    model.read_timeout_seconds = 60.0
    model.custom_role_conversions = None
    model.client = client
    model._prepare_completion_kwargs = lambda **kw: {'messages': kw['messages']}
    return model


@pytest.mark.case_id('UT-SDK-AUTO-85A0FBE8116B9F9A')
@pytest.mark.stage('D1')
def test_provider_context_overflow_recovery(monkeypatch):
    assert is_provider_context_overflow(_FakeProviderOverflow()) is True

    # 1. recover_step source-level rebuild re-dispatches FinalContext.messages.
    runtime = _FakeRuntime()
    rebuild_events = []

    def context_rebuild():
        rebuild_events.append('rebuild')
        return runtime.recover_step(model=None, memory=None, current_run_start_idx=0)

    client = _FakeClient([_FakeProviderOverflow(), _success_stream()])
    result = _build_model(client)(
        [{'role': 'user', 'content': 'original'}],
        _token_tracker=_StubTokenTracker(),
        context_rebuild=context_rebuild,
    )
    assert result.content == 'hello'
    assert len(rebuild_events) == 1
    assert runtime.recover_step_calls == 1
    assert len(client.completions.calls) == 2
    assert [m.content for m in client.completions.calls[1]['messages']] == ['rebuilt-step']

    # 2. recover_final_answer rebuild re-dispatches FinalContext.messages.
    runtime_final = _FakeRuntime()

    def context_rebuild_final():
        return runtime_final.recover_final_answer(
            model=None,
            memory=None,
            current_run_start_idx=0,
            task='task',
            final_answer_templates={},
        )

    client_final = _FakeClient([_FakeProviderOverflow(), _success_stream()])
    result_final = _build_model(client_final)(
        [{'role': 'user', 'content': 'original'}],
        _token_tracker=_StubTokenTracker(),
        context_rebuild=context_rebuild_final,
    )
    assert result_final.content == 'hello'
    assert runtime_final.recover_final_answer_calls == 1
    assert [m.content for m in client_final.completions.calls[1]['messages']] == ['rebuilt-final']

    # 3. safety gate: context_rebuild None -> Unsafe, no rebuild dispatched.
    client_unsafe = _FakeClient([_FakeProviderOverflow()])
    with pytest.raises(ModelInvocationTerminalError) as unsafe_error:
        _build_model(client_unsafe)(
            [{'role': 'user', 'content': 'original'}],
            _token_tracker=_StubTokenTracker(),
            context_rebuild=None,
        )
    assert unsafe_error.value.error_code == ModelErrorCode.CONTEXT_OVERFLOW
    assert "cannot be safely rebuilt" in str(unsafe_error.value)

    # 4. retry exhaustion: overflow persists across rebuilds -> Exhausted after two.
    rebuild_calls = []

    def context_rebuild_always_overflow():
        rebuild_calls.append('rebuild')
        return FinalContext(messages=[{'role': 'user', 'content': 'rebuilt'}])

    client_exhausted = _FakeClient([
        _FakeProviderOverflow(),
        _FakeProviderOverflow(),
        _FakeProviderOverflow(),
    ])
    with pytest.raises(ModelInvocationTerminalError) as exhausted_error:
        _build_model(client_exhausted)(
            [{'role': 'user', 'content': 'original'}],
            _token_tracker=_StubTokenTracker(),
            context_rebuild=context_rebuild_always_overflow,
        )
    assert exhausted_error.value.error_code == ModelErrorCode.CONTEXT_OVERFLOW
    assert "persisted after two recovery dispatches" in str(exhausted_error.value)
    assert len(rebuild_calls) == 2

    # 5. CoreAgent safety gate returns True without tool side effects, False with.
    agent = object.__new__(CoreAgent)
    agent._history_step_count = 0
    agent.memory = types.SimpleNamespace(steps=[types.SimpleNamespace(tool_calls=None)])
    assert agent._provider_overflow_recovery_safe() is True

    agent.memory = types.SimpleNamespace(steps=[
        types.SimpleNamespace(tool_calls=None),
        types.SimpleNamespace(tool_calls=[object()]),
    ])
    assert agent._provider_overflow_recovery_safe() is False

    # 6. concurrency permit released before re-entry (no permit leak).
    limiter = _FakeLimiter()
    monkeypatch.setattr(openai_llm, 'model_concurrency_limiter', limiter)
    client_permit = _FakeClient([_FakeProviderOverflow(), _success_stream()])

    def context_rebuild_permit():
        return FinalContext(messages=[{'role': 'user', 'content': 'rebuilt'}])

    result_permit = _build_model(client_permit, concurrency_limit=1)(
        [{'role': 'user', 'content': 'original'}],
        _token_tracker=_StubTokenTracker(),
        context_rebuild=context_rebuild_permit,
    )
    assert result_permit.content == 'hello'
    assert limiter.events == ['acquire', 'release', 'acquire', 'release']
