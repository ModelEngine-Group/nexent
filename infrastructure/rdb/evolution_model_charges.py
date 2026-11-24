# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Reserve before outbound dispatch, reconcile against provider-reported usage."""

from sqlalchemy import text

from contracts.evolution_metering import cost_in_micros
from infrastructure.rdb.client import get_db_session


def _lock(session, tenant):
    session.execute(text("""
        SELECT pg_advisory_xact_lock(hashtextextended('evolution-model-charge:' || :tenant, 0))
    """), {"tenant": tenant})


def reserve_model_call(tenant, user, model, attempt, allowance, tariff, output_tokens):
    reserved_micros = cost_in_micros(tariff.max_input_tokens, output_tokens,
                                    tariff.input_micros_per_million, tariff.output_micros_per_million)
    params = dict(tenant=tenant, user=user, model=model, attempt=attempt,
                  input=tariff.max_input_tokens, output=output_tokens, micros=reserved_micros,
                  input_rate=tariff.input_micros_per_million, output_rate=tariff.output_micros_per_million,
                  revision=allowance.revision())
    with get_db_session() as session:
        _lock(session, tenant)
        active = session.scalar(text("""
            SELECT attempt_id FROM nexent.evolution_generation_attempt_t WHERE attempt_id=:attempt
              AND tenant_id=:tenant AND created_by=:user AND model_id=:model AND metering_revision=:revision
              AND completed_at IS NULL AND NOT budget_stopped AND lease_until > clock_timestamp()
            FOR UPDATE
        """), params)
        if active is None:
            return None

        used_tokens, used_micros, exceeded = session.execute(text("""
            SELECT COALESCE(sum(COALESCE(reported_input + reported_output, reserved_input + reserved_output)), 0),
                   COALESCE(sum(COALESCE(reported_micros, reserved_micros)), 0),
                   COALESCE(bool_or(reported_input > reserved_input OR reported_output > reserved_output), false)
              FROM nexent.evolution_model_charge_t WHERE tenant_id=:tenant
               AND create_time >= (date_trunc('day', clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')
        """), params).one()
        if (exceeded or used_tokens + tariff.max_input_tokens + output_tokens > allowance.daily_tokens
                or used_micros + reserved_micros > allowance.daily_micros):
            session.execute(text("""
                UPDATE nexent.evolution_generation_attempt_t SET budget_stopped=TRUE WHERE attempt_id=:attempt
            """), params)
            return None
        return session.scalar(text("""
            INSERT INTO nexent.evolution_model_charge_t
                (tenant_id, attempt_id, reserved_input, reserved_output, reserved_micros, input_rate, output_rate)
            VALUES (:tenant, :attempt, :input, :output, :micros, :input_rate, :output_rate)
            RETURNING charge_id
        """), params)


def reconcile_model_call(tenant, charge_id, input_tokens, output_tokens):
    with get_db_session() as session:
        _lock(session, tenant)
        params = dict(tenant=tenant, charge=charge_id, input=input_tokens, output=output_tokens)
        row = session.execute(text("""
            SELECT attempt_id, reserved_input, reserved_output, input_rate, output_rate
            FROM nexent.evolution_model_charge_t WHERE charge_id=:charge AND tenant_id=:tenant
                AND reported_input IS NULL FOR UPDATE
        """), params).mappings().one_or_none()
        if row is None:
            return False
        # Persist overage before stopping the job. Later requests also see the exceeded bound.
        exceeded = input_tokens > row["reserved_input"] or output_tokens > row["reserved_output"]
        params["micros"] = cost_in_micros(input_tokens, output_tokens, row["input_rate"], row["output_rate"])
        session.execute(text("""
            UPDATE nexent.evolution_model_charge_t
               SET reported_input=:input, reported_output=:output, reported_micros=:micros
             WHERE charge_id=:charge AND tenant_id=:tenant
        """), params)
        if exceeded:
            session.execute(text("""
                UPDATE nexent.evolution_generation_attempt_t SET budget_stopped=TRUE WHERE attempt_id=:attempt
            """), {"attempt": row["attempt_id"]})
        return not exceeded
