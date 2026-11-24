# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Reserve before outbound dispatch, reconcile against provider-reported usage."""

from sqlalchemy import text

from contracts.evolution_metering import cost_in_micros
from infrastructure.rdb.client import get_db_session


def _lock(session, tenant):
    session.execute(text("""
        SELECT pg_advisory_xact_lock(hashtextextended('evolution-model-charge:' || :tenant, 0))
    """), {"tenant": tenant})


def _stop_budget(session, attempt, experiment):
    session.execute(text("""
        UPDATE nexent.evolution_generation_attempt_t SET budget_stopped=TRUE WHERE attempt_id=:attempt
    """), {"attempt": attempt})
    if experiment is not None:
        session.execute(text("""
            UPDATE nexent.evolution_experiment_t SET budget_stop_reason='experiment_model_budget_exceeded'
            WHERE experiment_id=:experiment AND budget_stop_reason IS NULL
        """), {"experiment": experiment})


def reserve_model_call(tenant, user, model, attempt, allowance, tariff, output_tokens, *, evaluation=False):
    reserved_micros = cost_in_micros(tariff.max_input_tokens, output_tokens,
                                    tariff.input_micros_per_million, tariff.output_micros_per_million)
    params = dict(tenant=tenant, user=user, model=model, attempt=attempt, evaluation=evaluation,
                  input=tariff.max_input_tokens, output=output_tokens, micros=reserved_micros,
                  input_rate=tariff.input_micros_per_million, output_rate=tariff.output_micros_per_million,
                  revision=allowance.revision())
    with get_db_session() as session:
        _lock(session, tenant)
        active = session.execute(text("""
            SELECT a.experiment_id, e.plan->'metering' AS limits
            FROM nexent.evolution_generation_attempt_t a
            LEFT JOIN nexent.evolution_experiment_t e ON e.experiment_id=a.experiment_id
            LEFT JOIN nexent.evolution_trial_t t ON t.trial_id=a.trial_id AND t.experiment_id=e.experiment_id
            WHERE a.attempt_id=:attempt AND a.tenant_id=:tenant AND a.created_by=:user
              AND a.metering_revision=:revision AND a.completed_at IS NULL AND NOT a.budget_stopped
              AND a.lease_until > clock_timestamp() AND (a.model_id IS NULL OR a.model_id=:model)
              AND CASE WHEN :evaluation THEN
                  e.tenant_id=:tenant AND e.created_by=:user AND NOT e.cancelled AND e.budget_stop_reason IS NULL
                  AND t.receipt_id=a.trial_receipt AND t.status='running' AND t.lease_until > clock_timestamp()
                  AND e.create_time + make_interval(secs => (e.plan->'budget'->>'max_elapsed_seconds')::int)
                      > clock_timestamp()
              ELSE a.experiment_id IS NULL AND a.model_id=:model END
            FOR UPDATE OF a
        """), params).mappings().one_or_none()
        if active is None:
            return None
        experiment = active["experiment_id"]
        params["experiment"] = experiment
        used_tokens, used_micros, exceeded = session.execute(text("""
            SELECT COALESCE(sum(COALESCE(reported_input + reported_output, reserved_input + reserved_output)), 0),
                   COALESCE(sum(COALESCE(reported_micros, reserved_micros)), 0),
                   COALESCE(bool_or(reported_input > reserved_input OR reported_output > reserved_output), false)
              FROM nexent.evolution_model_charge_t WHERE tenant_id=:tenant
               AND (experiment_id IS NOT NULL)=:evaluation
               AND create_time >= (date_trunc('day', clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')
        """), params).one()
        tokens = tariff.max_input_tokens + output_tokens
        daily_limit = exceeded or used_tokens + tokens > allowance.daily_tokens or used_micros + reserved_micros > allowance.daily_micros
        if daily_limit or experiment is not None and _exceeds_experiment(session, params, active["limits"], tokens):
            _stop_budget(session, attempt, experiment)
            return None
        return session.scalar(text("""
            INSERT INTO nexent.evolution_model_charge_t
                (tenant_id, attempt_id, experiment_id, model_id, reserved_input, reserved_output, reserved_micros,
                 input_rate, output_rate)
            VALUES (:tenant, :attempt, :experiment, :model, :input, :output, :micros, :input_rate, :output_rate)
            RETURNING charge_id
        """), params)


def _exceeds_experiment(session, params, limits, tokens):
    used_tokens, used_micros = session.execute(text("""
        SELECT COALESCE(sum(COALESCE(reported_input + reported_output, reserved_input + reserved_output)), 0),
               COALESCE(sum(COALESCE(reported_micros, reserved_micros)), 0)
          FROM nexent.evolution_model_charge_t WHERE tenant_id=:tenant AND experiment_id=:experiment
    """), params).one()
    return (used_tokens + tokens > limits["max_model_tokens"]
            or used_micros + params["micros"] > limits["max_model_micros"])


def reconcile_model_call(tenant, charge_id, input_tokens, output_tokens):
    with get_db_session() as session:
        _lock(session, tenant)
        params = dict(tenant=tenant, charge=charge_id, input=input_tokens, output=output_tokens)
        row = session.execute(text("""
            SELECT attempt_id, experiment_id, reserved_input, reserved_output, input_rate, output_rate
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
            _stop_budget(session, row["attempt_id"], row["experiment_id"])
        return not exceeded
