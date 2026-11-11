# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from starlette.responses import Response

from contracts.agent import AgentRequest
from contracts.agentos import CompatibilityConversationRun
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.agent_admission import AdmissionClaim, AdmissionRequestConflict
from runtime.agentos import admission

RUN_ID = "a" * 32
ACTOR = ServicePrincipal("actor", "tenant")


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [False, True])
async def test_management_handoff_validates_existing_claim_without_claiming_again(monkeypatch, authorized):
    from management.services.agent import conversation_submission as submission

    sent = CompatibilityConversationRun(
        request={"query": "question", "conversation_id": 42, "agent_id": 7, "is_debug": False},
        idempotency_key="client-123", claimed_run_id=RUN_ID,
    )
    async def direct(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    claim = MagicMock(side_effect=AssertionError("A received handoff must retain its original claim"))
    validate = MagicMock(return_value=authorized)
    monkeypatch.setattr(submission, "_control_io", direct)
    monkeypatch.setattr(submission, "conversation_belongs_to", MagicMock(return_value=True))
    monkeypatch.setattr(submission, "claim_conversation_run", claim)
    monkeypatch.setattr(submission, "authorize_conversation_dispatch", validate, raising=False)
    dispatch = AsyncMock(return_value=Response(headers={"conversation_id": "42"}))
    if authorized:
        response = await submission.submit_conversation(sent, ACTOR.user_id, ACTOR.tenant_id, dispatch)
        assert response.headers["X-AgentOS-Run-ID"] == RUN_ID
        dispatch.assert_awaited_once_with(sent, ACTOR.user_id, ACTOR.tenant_id)
    else:
        with pytest.raises(HTTPException) as error:
            await submission.submit_conversation(sent, ACTOR.user_id, ACTOR.tenant_id, dispatch)
        assert (error.value.status_code, error.value.detail) == (409, {"code": "AGENTOS_ADMISSION_NOT_PENDING"})
        dispatch.assert_not_called()
    scope = submission.conversation_claim_scope(ACTOR.user_id, ACTOR.tenant_id, sent.idempotency_key)
    fingerprint = submission.conversation_request_fingerprint(
        sent.model_dump(mode="json", exclude={"idempotency_key", "claimed_run_id"}),
    )
    validate.assert_called_once_with(scope, fingerprint, RUN_ID, ACTOR.user_id, ACTOR.tenant_id, consume=False)
    claim.assert_not_called()


def test_read_only_claim_validation_retains_scope_predicates_without_mutation(monkeypatch):
    from infrastructure.rdb import agent_admission

    session = MagicMock()
    session.scalar.return_value = "claim-scope"
    context = MagicMock()
    context.__enter__.return_value = session
    monkeypatch.setattr(agent_admission, "get_db_session", lambda: context)
    membership = MagicMock(return_value=True)
    monkeypatch.setattr(agent_admission, "tenant_membership_matches", membership)

    assert agent_admission.authorize_conversation_dispatch(
        "claim-scope", "fingerprint", RUN_ID, ACTOR.user_id, ACTOR.tenant_id, consume=False,
    )
    membership.assert_called_once_with(session, ACTOR.user_id, ACTOR.tenant_id)
    query = session.scalar.call_args.args[0]
    assert query.compile().params == {
        "scope_sha256_1": "claim-scope", "request_sha256_1": "fingerprint", "run_id_1": RUN_ID,
        "created_by_1": ACTOR.user_id, "tenant_id_1": ACTOR.tenant_id, "status_1": "pending", "delete_flag_1": "N",
    }
    session.execute.assert_not_called()


def test_handoff_read_and_late_rejection_preserve_the_winning_staged_run(monkeypatch):
    from contextlib import contextmanager

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from infrastructure.rdb import agent_admission

    engine = create_engine("sqlite://", execution_options={"schema_translate_map": {agent_admission.SCHEMA: None}})

    @contextmanager
    def session_scope():
        with Session(engine) as session, session.begin():
            yield session

    monkeypatch.setattr(agent_admission, "get_db_session", session_scope)
    monkeypatch.setattr(agent_admission, "tenant_membership_matches", lambda session, user, tenant: True)
    try:
        with engine.begin() as connection:
            connection.execute(text("""CREATE TABLE conversation_run_admission_t (
                scope_sha256 TEXT PRIMARY KEY, run_id TEXT, request_sha256 TEXT,
                created_by TEXT, tenant_id TEXT, status TEXT, delete_flag TEXT,
                conversation_id INTEGER, journal_available BOOLEAN, prepared_message_index INTEGER,
                updated_by TEXT, update_time TIMESTAMP
            )"""))
            connection.execute(text("""INSERT INTO conversation_run_admission_t
                (scope_sha256, run_id, request_sha256, created_by, tenant_id, status, delete_flag)
                VALUES (:scope, :run_id, 'fingerprint', 'actor', 'tenant', 'pending', 'N')"""), [
                    {"scope": "scope", "run_id": RUN_ID}, {"scope": "unstaged", "run_id": "b" * 32},
                ])
        args = ("scope", "fingerprint", RUN_ID, ACTOR.user_id, ACTOR.tenant_id)
        assert agent_admission.authorize_conversation_dispatch(*args, consume=False)
        assert agent_admission.authorize_conversation_dispatch(*args, consume=False)
        for index, value in enumerate(("other-scope", "other-fingerprint", "b" * 32, "other-user", "other-tenant")):
            changed_arguments = list(args)
            changed_arguments[index] = value
            assert not agent_admission.authorize_conversation_dispatch(*changed_arguments, consume=False)
        # The existing Runtime still consumes the pending claim exactly once.
        assert agent_admission.authorize_conversation_dispatch(*args)
        assert not agent_admission.authorize_conversation_dispatch(*args)
        with engine.begin() as connection:
            connection.execute(text("""UPDATE conversation_run_admission_t
                SET prepared_message_index=3, conversation_id=42 WHERE scope_sha256='scope'"""))
        # A losing Management preparation must not reject the winner's durable marker.
        assert not agent_admission.set_conversation_admission(
            "scope", RUN_ID, ACTOR.user_id, ACTOR.tenant_id, conversation_id=None, journal_available=False,
        )
        assert agent_admission.set_conversation_admission(
            "unstaged", "b" * 32, ACTOR.user_id, ACTOR.tenant_id, conversation_id=None, journal_available=False,
        )
        with engine.connect() as connection:
            row = connection.execute(text("""SELECT status, conversation_id, prepared_message_index
                FROM conversation_run_admission_t WHERE scope_sha256='scope'""")).one()
            assert tuple(row) == ("dispatching", 42, 3)
            assert connection.scalar(text("SELECT status FROM conversation_run_admission_t WHERE scope_sha256='unstaged'")) == "rejected"
    finally:
        engine.dispose()


def payload(query="question", **values):
    return CompatibilityConversationRun(
        request={"query": query, **values}, idempotency_key="client-123",
    )


@pytest.fixture
def claim_store(mocker):
    records = {}

    async def control_io(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    def claim(scope, fingerprint, user_id, tenant_id):
        assert (user_id, tenant_id) == (ACTOR.user_id, ACTOR.tenant_id)
        if scope not in records:
            records[scope] = (fingerprint, "pending", None)
            return AdmissionClaim(RUN_ID, "pending", None, False, True)
        expected, status, conversation_id = records[scope]
        if fingerprint != expected:
            raise AdmissionRequestConflict
        return AdmissionClaim(RUN_ID, status, conversation_id, bool(conversation_id), False)

    def bind(scope, run_id, user_id, tenant_id, *, conversation_id, journal_available):
        assert (run_id, user_id, tenant_id) == (RUN_ID, ACTOR.user_id, ACTOR.tenant_id)
        expected = records[scope][0]
        records[scope] = (expected, "admitted" if conversation_id is not None else "rejected", conversation_id)
        return True

    mocker.patch.object(admission, "_control_io", side_effect=control_io)
    mocker.patch.object(admission, "claim_conversation_run", side_effect=claim)
    mocker.patch.object(admission, "set_conversation_admission", side_effect=bind)
    mocker.patch.object(admission, "conversation_belongs_to", return_value=True)
    return bind


@pytest.mark.asyncio
async def test_concurrent_and_lost_response_retries_reuse_one_run(claim_store):
    sent = payload()
    first_request = AgentRequest.model_validate(sent.request)
    started = asyncio.Event()
    release = asyncio.Event()
    never_execute = AsyncMock()

    async def execute():
        assert first_request._projection_run_id == RUN_ID
        started.set()
        await release.wait()
        claim_store(first_request._run_admission_scope, RUN_ID, ACTOR.user_id, ACTOR.tenant_id,
                    conversation_id=42, journal_available=True)
        return Response(headers={"conversation_id": "42"})

    first = asyncio.create_task(admission.admit_conversation_run(sent, first_request, ACTOR, execute))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        pending = await admission.admit_conversation_run(sent, AgentRequest(query="question"), ACTOR, never_execute)
        assert pending.status_code == 202
        assert pending.headers["X-AgentOS-Run-ID"] == RUN_ID
        assert json.loads(pending.body)["status"] == "pending"
    finally:
        release.set()
        original = await first
    assert original.headers["X-AgentOS-Run-ID"] == RUN_ID

    replay = await admission.admit_conversation_run(sent, AgentRequest(query="question"), ACTOR, never_execute)
    assert replay.status_code == 202 and replay.headers["conversation_id"] == "42"
    assert json.loads(replay.body) == {
        "run_id": RUN_ID, "status": "admitted", "conversation_id": 42, "journal_available": True,
    }
    admission.conversation_belongs_to.assert_called_once_with(42, user_id="actor", tenant_id="tenant")
    never_execute.assert_not_called()


@pytest.mark.asyncio
async def test_conflict_and_unauthorized_conversation_never_execute(claim_store):
    sent = payload()
    await admission.admit_conversation_run(
        sent, AgentRequest(query="question"), ACTOR, AsyncMock(return_value=Response()),
    )
    execute = AsyncMock()
    with pytest.raises(HTTPException) as conflict:
        await admission.admit_conversation_run(payload("changed"), AgentRequest(query="changed"), ACTOR, execute)
    assert conflict.value.status_code == 409

    admission.conversation_belongs_to.return_value = False
    with pytest.raises(HTTPException) as forbidden:
        await admission.admit_conversation_run(
            payload(conversation_id=42), AgentRequest(query="question", conversation_id=42), ACTOR, execute,
        )
    assert forbidden.value.status_code == 404
    execute.assert_not_called()


@pytest.mark.asyncio
async def test_known_rejection_is_retained_with_original_run_id(claim_store):
    sent = payload()
    execute = AsyncMock(side_effect=HTTPException(status_code=429, headers={"Retry-After": "7"}))
    with pytest.raises(HTTPException) as first:
        await admission.admit_conversation_run(sent, AgentRequest(query="question"), ACTOR, execute)
    assert first.value.headers["X-AgentOS-Run-ID"] == RUN_ID
    assert first.value.headers["Retry-After"] == "7"

    retry = await admission.admit_conversation_run(sent, AgentRequest(query="question"), ACTOR, execute)
    assert retry.status_code == 409
    assert json.loads(retry.body)["status"] == "rejected"
    assert retry.headers["X-AgentOS-Run-ID"] == RUN_ID
    execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_outcome_does_not_reacquire_or_launch_another_run(claim_store):
    sent = payload()
    execute = AsyncMock(side_effect=HTTPException(status_code=500))
    with pytest.raises(HTTPException) as first:
        await admission.admit_conversation_run(sent, AgentRequest(query="question"), ACTOR, execute)
    assert first.value.headers["X-AgentOS-Run-ID"] == RUN_ID

    retry = await admission.admit_conversation_run(sent, AgentRequest(query="question"), ACTOR, execute)
    assert retry.status_code == 202 and retry.headers["Retry-After"] == "1"
    assert json.loads(retry.body)["status"] == "pending"
    assert retry.headers["X-AgentOS-Run-ID"] == RUN_ID
    execute.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("acknowledged", [True, False])
async def test_management_owns_claim_and_retries_never_dispatch(monkeypatch, acknowledged):
    from contracts.errors.exceptions import RuntimeServiceTimeoutError
    from management.services.agent import conversation_submission as submission

    async def control_io(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    state = {}
    sent = payload()

    def claim(scope, fingerprint, user_id, tenant_id):
        assert (user_id, tenant_id) == (ACTOR.user_id, ACTOR.tenant_id)
        if not state:
            state.update(scope=scope, fingerprint=fingerprint)
            return AdmissionClaim(RUN_ID, "pending", None, False, True)
        assert scope == state["scope"]
        if fingerprint != state["fingerprint"]:
            raise AdmissionRequestConflict
        conversation_id = state.get("conversation_id")
        return AdmissionClaim(RUN_ID, "admitted" if conversation_id else "pending", conversation_id, bool(conversation_id), False)

    async def dispatch(command, user_id, tenant_id):
        assert command.claimed_run_id == RUN_ID
        assert command.idempotency_key == sent.idempotency_key
        assert (user_id, tenant_id) == (ACTOR.user_id, ACTOR.tenant_id)
        if acknowledged:
            state["conversation_id"] = 42
            return Response(headers={"conversation_id": "42"})
        raise RuntimeServiceTimeoutError("response lost")

    transport = AsyncMock(side_effect=dispatch)
    monkeypatch.setattr(submission, "_control_io", control_io)
    monkeypatch.setattr(submission, "claim_conversation_run", claim)
    monkeypatch.setattr(submission, "conversation_belongs_to", lambda *args, **kwargs: True)

    if acknowledged:
        response = await submission.submit_conversation(sent, ACTOR.user_id, ACTOR.tenant_id, transport)
        assert response.headers["X-AgentOS-Run-ID"] == RUN_ID
    else:
        with pytest.raises(RuntimeServiceTimeoutError):
            await submission.submit_conversation(sent, ACTOR.user_id, ACTOR.tenant_id, transport)

    replay = await submission.submit_conversation(sent, ACTOR.user_id, ACTOR.tenant_id, transport)
    assert replay.status_code == 202
    assert json.loads(replay.body)["status"] == ("admitted" if acknowledged else "pending")
    assert replay.headers["X-AgentOS-Run-ID"] == RUN_ID
    transport.assert_awaited_once()


@pytest.mark.asyncio
async def test_management_rejects_unowned_conversation_before_claiming(monkeypatch):
    from management.services.agent import conversation_submission as submission

    async def control_io(_task, function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(submission, "_control_io", control_io)
    monkeypatch.setattr(submission, "conversation_belongs_to", lambda *args, **kwargs: False)
    claim = AsyncMock()
    monkeypatch.setattr(submission, "claim_conversation_run", claim)
    dispatch = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await submission.submit_conversation(payload(conversation_id=42), ACTOR.user_id, ACTOR.tenant_id, dispatch)
    assert error.value.status_code == 404
    claim.assert_not_called()
    dispatch.assert_not_called()


def test_claimed_run_id_does_not_change_legacy_request_fingerprint():
    from infrastructure.rdb.agent_admission import conversation_claim_scope, conversation_request_fingerprint

    sent = payload()
    assert "claimed_run_id" not in sent.model_dump_json()
    normalized = sent.model_dump(mode="json", exclude={"idempotency_key"})
    assert normalized == {"request": {"query": "question"}, "resume": False, "language": "zh", "timezone": None}
    claimed = sent.model_copy(update={"claimed_run_id": RUN_ID})
    assert CompatibilityConversationRun.model_validate_json(claimed.model_dump_json()) == claimed
    assert conversation_request_fingerprint(normalized) == conversation_request_fingerprint(
        claimed.model_dump(mode="json", exclude={"idempotency_key", "claimed_run_id"}),
    )
    assert conversation_claim_scope("actor", "tenant", "client-123") != conversation_claim_scope("actor", "other", "client-123")


@pytest.mark.asyncio
async def test_runtime_rejects_claimed_handoff_before_side_effects_if_fence_denies(claim_store, mocker):
    sent = payload().model_copy(update={"claimed_run_id": RUN_ID})
    consume = mocker.patch.object(admission, "authorize_conversation_dispatch", return_value=False)
    execute = AsyncMock()
    request = AgentRequest(query="question")
    with pytest.raises(HTTPException) as error:
        await admission.admit_conversation_run(sent, request, ACTOR, execute)
    assert error.value.status_code == 409
    assert consume.call_args.args[2:] == (RUN_ID, ACTOR.user_id, ACTOR.tenant_id)
    assert request._projection_run_id is None
    admission.claim_conversation_run.assert_not_called()
    execute.assert_not_called()
