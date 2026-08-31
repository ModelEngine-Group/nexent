"""Durable run, interaction, execution receipt and event persistence models."""

from sqlalchemy import BigInteger, Column, Integer, JSON, String, Text, TIMESTAMP

from .db_models import SCHEMA, SimpleTableBase


class HumanRun(SimpleTableBase):
    __tablename__ = "human_run_t"
    __table_args__ = {"schema": SCHEMA}

    run_id = Column(String(36), primary_key=True)
    tenant_id = Column(String(100), nullable=False)
    user_id = Column(String(100), nullable=False)
    conversation_id = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False)
    request_payload = Column(Text, nullable=False)
    checkpoint = Column(Text)
    catalog_digest = Column(String(64))
    executor_digest = Column(String(64))
    plan = Column(Text)
    plan_version = Column(Integer, nullable=False, default=0)
    fence = Column(Integer, nullable=False, default=0)
    lock_owner = Column(String(200))
    lock_until = Column(TIMESTAMP(timezone=True))
    pause_requested = Column(Integer, nullable=False, default=0)
    event_seq = Column(BigInteger, nullable=False, default=0)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False)


class HumanRequest(SimpleTableBase):
    __tablename__ = "human_request_t"
    __table_args__ = {"schema": SCHEMA}

    request_id = Column(String(36), primary_key=True)
    run_id = Column(String(36), nullable=False, index=True)
    kind = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    slot = Column(String(100), nullable=False)
    digest = Column(String(64), nullable=False)
    payload = Column(Text, nullable=False)
    decision = Column(Text)
    idempotency_key = Column(String(100))
    decision_digest = Column(String(64))
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)


class HumanExecution(SimpleTableBase):
    __tablename__ = "human_execution_t"
    __table_args__ = {"schema": SCHEMA}

    run_id = Column(String(36), primary_key=True)
    slot = Column(String(100), primary_key=True)
    tool = Column(String(200), nullable=False)
    digest = Column(String(64), nullable=False)
    arguments = Column(Text, nullable=False)
    status = Column(String(32), nullable=False)
    result = Column(Text)


class HumanEvent(SimpleTableBase):
    __tablename__ = "human_event_t"
    __table_args__ = {"schema": SCHEMA}

    run_id = Column(String(36), primary_key=True)
    seq = Column(BigInteger, primary_key=True)
    payload = Column(JSON, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)
