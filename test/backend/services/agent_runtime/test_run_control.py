from backend.services.agent_runtime.run_control import (
    RuntimeRunControlRegistry,
    RuntimeRunHandle,
)


class FakeRuntime:
    def __init__(self) -> None:
        self.stop_calls = []

    def request_stop(self, run_id: str) -> bool:
        self.stop_calls.append(run_id)
        return True


def test_run_control_stops_current_run_by_conversation_and_user():
    registry = RuntimeRunControlRegistry()
    runtime = FakeRuntime()
    handle = RuntimeRunHandle(
        run_id="run-1",
        conversation_id=10,
        user_id="user-1",
        runtime=runtime,
    )
    registry.register(handle)

    assert registry.request_stop(conversation_id=10, user_id="user-1") is True
    assert runtime.stop_calls == ["run-1"]


def test_stale_unregister_does_not_remove_replacement_run():
    registry = RuntimeRunControlRegistry()
    first_runtime = FakeRuntime()
    second_runtime = FakeRuntime()
    registry.register(RuntimeRunHandle("run-1", 10, "user-1", first_runtime))
    registry.register(RuntimeRunHandle("run-2", 10, "user-1", second_runtime))

    registry.unregister(run_id="run-1", conversation_id=10, user_id="user-1")

    assert registry.request_stop(conversation_id=10, user_id="user-1") is True
    assert first_runtime.stop_calls == []
    assert second_runtime.stop_calls == ["run-2"]
