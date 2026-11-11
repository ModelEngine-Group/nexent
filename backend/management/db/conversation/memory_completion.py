# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Projection-owned queue for prepared conversation Memory completion."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import Column, Integer, String, TIMESTAMP, func, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert

from contracts.conversation import MessageSource
from infrastructure.rdb.base import SCHEMA, TableBase
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.agent_admission import ConversationRunAdmission
from infrastructure.rdb.conversation_record import ConversationMessage, ConversationRecord
from infrastructure.rdb.conversation_state import tenant_membership_matches
from management.db.conversation.projection_receipt import ConversationProjectionReceipt

TURN_COMPLETED = "turn_completed"
FINAL_ANSWER = "final_answer"
_MAX_ATTEMPTS = 5
_LEASE = timedelta(minutes=5)


class MemoryCompletion(TableBase):
    __tablename__ = "conversation_memory_completion_t"
    __table_args__ = {"schema": SCHEMA}

    job_id = Column(String(48), primary_key=True)
    run_id = Column(String(32), nullable=False)
    job_type = Column(String(20), nullable=False)
    agent_id = Column(Integer, nullable=False)
    source_message_id = Column(Integer)
    attempts = Column(Integer, nullable=False, server_default="0")
    next_attempt_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    lease_token = Column(String(32))
    finished_at = Column(TIMESTAMP(timezone=True))
    selected_items = Column(JSONB(none_as_null=True))


@dataclass(frozen=True)
class MemoryJob:
    run_id: str
    job_type: str
    agent_id: int
    token: str
    attempts: int
    selected_items: list[str] | None
    source_message_id: int | None = None


@dataclass(frozen=True)
class MemorySource:
    tenant_id: str
    user_id: str
    conversation_id: int
    message_id: int
    answer: str
    query: str


def _job_id(run_id: str, job_type: str) -> str:
    return f"{run_id}:{job_type}"


def enqueue(session, run_id: str, agent_id: int, actor: str, status: str, answer: str, *,
            source_message_id: int | None = None) -> None:
    types = ([TURN_COMPLETED] if status == "completed" else []) + ([FINAL_ANSWER] if answer.strip() else [])
    if types:
        session.execute(insert(MemoryCompletion).values([
            {"job_id": _job_id(run_id, job_type), "run_id": run_id, "job_type": job_type, "agent_id": agent_id,
             "source_message_id": source_message_id, "created_by": actor, "updated_by": actor, "delete_flag": "N"}
            for job_type in types
        ]).on_conflict_do_nothing(index_elements=[MemoryCompletion.job_id]))


def claim() -> MemoryJob | None:
    queue = MemoryCompletion
    with get_db_session() as session:
        row = session.scalar(select(queue).where(
            queue.finished_at.is_(None), queue.delete_flag == "N", queue.next_attempt_at <= func.now(),
        ).order_by(queue.next_attempt_at, queue.job_id).limit(1).with_for_update(skip_locked=True))
        if row is None:
            return None
        if row.attempts >= _MAX_ATTEMPTS:
            row.finished_at = func.now()
            row.lease_token = None
            row.selected_items = None
            return None
        row.lease_token = uuid4().hex
        row.attempts += 1
        row.next_attempt_at = func.now() + _LEASE
        return MemoryJob(
            row.run_id, row.job_type, row.agent_id, row.lease_token, row.attempts, row.selected_items, row.source_message_id,
        )


def _leased(job):
    queue = MemoryCompletion
    return (
        queue.job_id == _job_id(job.run_id, job.job_type), queue.lease_token == job.token,
        queue.finished_at.is_(None), queue.delete_flag == "N", queue.next_attempt_at > func.now(),
    )


def read_source(job: MemoryJob) -> MemorySource | None:
    receipt = ConversationProjectionReceipt
    message = ConversationMessage
    conversation = ConversationRecord
    with get_db_session() as session:
        row = session.execute(select(receipt.tenant_id, receipt.created_by, message).join(
            message, message.message_id == receipt.message_id,
        ).join(conversation, conversation.conversation_id == message.conversation_id).where(
            receipt.run_id == job.run_id, receipt.delete_flag == "N",
            message.created_by == receipt.created_by, message.delete_flag == "N",
            message.message_role == "assistant",
            message.message_source.in_((MessageSource.CHAT.value, MessageSource.AUTOMATION.value)),
            conversation.created_by == receipt.created_by, conversation.delete_flag == "N",
            select(MemoryCompletion.run_id).where(*_leased(job)).exists(),
        )).one_or_none()
        if row is None or not tenant_membership_matches(session, row.created_by, row.tenant_id):
            return None
        assistant = row[2]
        if job.job_type == TURN_COMPLETED and assistant.status != "completed":
            return None
        prompt = select(message.message_content).where(
            message.conversation_id == assistant.conversation_id, message.created_by == row.created_by,
            message.message_index == assistant.message_index - 1, message.delete_flag == "N",
            message.message_role == "user", message.message_source == assistant.message_source,
        )
        if assistant.message_source == MessageSource.AUTOMATION.value:
            if job.source_message_id is None:
                return None
            prompt = prompt.where(message.message_id == job.source_message_id)
        query = session.scalar(prompt.limit(1))
        if assistant.message_source == MessageSource.CHAT.value:
            admission = ConversationRunAdmission
            context = session.scalar(select(admission.prepared_user_turn).where(
                admission.run_id == job.run_id, admission.conversation_id == assistant.conversation_id,
                admission.prepared_assistant_id == assistant.message_id, admission.created_by == row.created_by,
                admission.tenant_id == row.tenant_id, admission.status == "admitted", admission.delete_flag == "N",
            ).limit(1))
            if isinstance(context, dict) and "omitted_user_query" in context:
                if context.get("memory_agent_id") != job.agent_id or type(context["omitted_user_query"]) is not str:
                    return None
                query = context["omitted_user_query"]
        if query is None:
            return None
        return MemorySource(
            row.tenant_id, row.created_by, assistant.conversation_id, assistant.message_id,
            assistant.message_content or "", query,
        )


def checkpoint(job: MemoryJob, items: list[str]) -> bool:
    with get_db_session() as session:
        return bool(session.execute(update(MemoryCompletion).where(*_leased(job)).values(selected_items=items)).rowcount)


def settle(job: MemoryJob, *, retry: bool) -> bool:
    values = {"lease_token": None}
    if retry and job.attempts < _MAX_ATTEMPTS:
        values["next_attempt_at"] = func.now() + timedelta(seconds=15 * job.attempts)
    else:
        values.update(finished_at=func.now(), selected_items=None)
    with get_db_session() as session:
        return bool(session.execute(update(MemoryCompletion).where(*_leased(job)).values(**values)).rowcount)
