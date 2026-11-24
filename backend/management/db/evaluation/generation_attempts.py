# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Persist candidate model admission before any model request leaves Management."""

from sqlalchemy import text

from contracts.constants import environment
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from infrastructure.rdb.client import get_db_session


def reserve(tenant, user, source, model, *, metering_revision=None):
    with get_db_session() as session:
        params = dict(tenant=tenant, user=user, source=source, model=model,
                      seconds=environment.EVOLUTION_GENERATION_TIMEOUT_SECONDS, metered=metering_revision)
        session.execute(text("""
            SELECT pg_advisory_xact_lock(hashtextextended('evolution-generation:' || :tenant, 0))
        """), params)
        daily, source_daily = session.execute(text("""
            SELECT count(*), count(*) FILTER (WHERE source_digest=:source)
            FROM nexent.evolution_generation_attempt_t
            WHERE tenant_id=:tenant
              AND create_time >= date_trunc('day', clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
        """), params).one()
        if (daily >= environment.EVOLUTION_GENERATION_DAILY_ATTEMPTS
                or source_daily >= environment.EVOLUTION_GENERATION_SOURCE_ATTEMPTS):
            raise AppException(ErrorCode.COMMON_RATE_LIMIT_EXCEEDED, "Candidate generation attempt limit reached")
        active = session.scalar(text("""
            SELECT count(*) FROM nexent.evolution_generation_attempt_t
            WHERE tenant_id=:tenant AND completed_at IS NULL AND lease_until > clock_timestamp()
        """), params)
        if active >= environment.EVOLUTION_GENERATION_CONCURRENCY:
            raise AppException(ErrorCode.COMMON_RATE_LIMIT_EXCEEDED, "Candidate generation is at its concurrency limit")
        return session.scalar(text("""
            INSERT INTO nexent.evolution_generation_attempt_t
                (tenant_id, source_digest, model_id, created_by, lease_until, metering_revision)
            VALUES (:tenant, :source, :model, :user, clock_timestamp() + make_interval(secs=>:seconds), :metered)
            RETURNING attempt_id
        """), params)


def complete(tenant, attempt_id):
    with get_db_session() as session:
        return bool(session.scalar(text("""
            UPDATE nexent.evolution_generation_attempt_t SET completed_at=clock_timestamp()
            WHERE tenant_id=:tenant AND attempt_id=:attempt AND completed_at IS NULL AND NOT budget_stopped
              AND lease_until > clock_timestamp()
              AND (metering_revision IS NULL OR EXISTS (
                  SELECT 1 FROM nexent.evolution_model_charge_t WHERE attempt_id=:attempt AND tenant_id=:tenant
              ))
            RETURNING attempt_id
        """), dict(tenant=tenant, attempt=attempt_id)))



def stopped(tenant, attempt_id):
    with get_db_session() as session:
        return bool(session.scalar(text("""
            SELECT budget_stopped FROM nexent.evolution_generation_attempt_t
            WHERE tenant_id=:tenant AND attempt_id=:attempt
        """), dict(tenant=tenant, attempt=attempt_id)))
