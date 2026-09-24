import pytest

from services import workbench_creation_history_service as service


def _config(mode="skill_create"):
    return {
        "schema_version": 3,
        "mode": mode,
        "generation_config": {"deep_thinking": False},
        "agent_mounts": [],
        "skill_mounts": [],
    }


def _prepare(**overrides):
    values = {
        "conversation_id": None,
        "mode": "skill_create",
        "query": "Create a skill",
        "minio_files": None,
        "workbench_config": _config(),
        "agent_id": None,
        "user_id": "user-a",
        "tenant_id": "tenant-a",
    }
    values.update(overrides)
    return service.prepare_creation_history(**values)


def test_prepare_rejects_unsupported_mode():
    with pytest.raises(ValueError, match="Unsupported"):
        _prepare(mode="single_agent_chat")


@pytest.mark.parametrize(
    "updates",
    [
        {"retry_user_message_id": 10},
        {"workbench_config": None},
        {"mode": "agent_create", "workbench_config": _config("skill_create")},
    ],
)
def test_prepare_rejects_invalid_new_conversation(updates):
    with pytest.raises(ValueError):
        _prepare(**updates)


def test_prepare_rejects_inaccessible_existing_conversation(monkeypatch):
    monkeypatch.setattr(service, "get_conversation_history", lambda *_args: None)

    with pytest.raises(ValueError, match="accessible creation session"):
        _prepare(conversation_id=42, workbench_config=None)


def test_retry_requires_existing_assistant_response(monkeypatch):
    monkeypatch.setattr(
        service,
        "get_conversation_history",
        lambda *_args: {
            "workbench_config": _config(),
            "message_records": [
                {
                    "message_id": 10,
                    "message_index": 0,
                    "role": "user",
                    "message_content": "Create a skill",
                    "minio_files": None,
                }
            ],
        },
    )

    with pytest.raises(ValueError, match="no assistant response"):
        _prepare(
            conversation_id=42,
            workbench_config=None,
            retry_user_message_id=10,
        )


@pytest.mark.asyncio
async def test_persist_stream_skips_invalid_events_and_marks_error(monkeypatch):
    saved = []
    monkeypatch.setattr(
        service,
        "save_message",
        lambda message, **kwargs: saved.append((message, kwargs)) or 100,
    )
    monkeypatch.setattr(service, "save_message_unit", lambda **_kwargs: None)

    async def stream():
        yield "event: ping\n\n"
        yield "data: not-json\n\n"
        yield "data: []\n\n"
        yield 'data: {"type": 1}\n\n'
        yield 'data: {"type": "progress", "content": {"step": 1}}\n\n'
        yield 'data: {"type": "error", "content": "failed"}\n\n'

    output = [
        item
        async for item in service.persist_creation_stream(
            stream(),
            conversation_id=42,
            assistant_index=1,
            user_id="user-a",
            tenant_id="tenant-a",
        )
    ]

    assert len(output) == 6
    message, kwargs = saved[0]
    assert kwargs["status"] == "failed"
    assert [unit.type for unit in message.message] == ["progress", "error"]
    assert message.message[0].content == '{"step": 1}'


@pytest.mark.asyncio
async def test_persist_stream_marks_cancelled_generator_stopped(monkeypatch):
    saved = []
    monkeypatch.setattr(
        service,
        "save_message",
        lambda message, **kwargs: saved.append((message, kwargs)) or 100,
    )
    monkeypatch.setattr(service, "save_message_unit", lambda **_kwargs: None)

    async def stream():
        yield 'data: {"type": "progress", "content": "one"}\n\n'
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        _ = [
            item
            async for item in service.persist_creation_stream(
                stream(),
                conversation_id=42,
                assistant_index=1,
                user_id="user-a",
                tenant_id="tenant-a",
            )
        ]

    assert saved[0][1]["status"] == "stopped"


@pytest.mark.asyncio
async def test_persist_stream_swallows_transcript_persistence_failure(monkeypatch):
    monkeypatch.setattr(
        service,
        "save_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database down")),
    )

    async def stream():
        yield 'data: {"type": "done", "content": ""}\n\n'

    output = [
        item
        async for item in service.persist_creation_stream(
            stream(),
            conversation_id=42,
            assistant_index=1,
            user_id="user-a",
            tenant_id="tenant-a",
        )
    ]

    assert len(output) == 1
