# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Reserve before outbound dispatch, reconcile against provider-reported usage."""

from sqlalchemy import text

from contracts.evolution_metering import cost_in_micros
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.evolution_review_authority import authorized_review_turn


def lock_model_charges(session, tenant):
    session.execute(text("""
        SELECT pg_advisory_xact_lock(hashtextextended('evolution-model-charge:' || :tenant, 0))
    """), {"tenant": tenant})


def _stop_budget(session, attempt, experiment, confirmation_lock):
    session.execute(text("""
        UPDATE nexent.evolution_generation_attempt_t SET budget_stopped=TRUE WHERE attempt_id=:attempt
    """), {"attempt": attempt})
    if experiment is not None:
        session.execute(text("""
            UPDATE nexent.evolution_experiment_t SET budget_stop_reason='experiment_model_budget_exceeded'
            WHERE experiment_id=:experiment AND budget_stop_reason IS NULL
        """), {"experiment": experiment})
    if confirmation_lock is not None:
        session.execute(text("""
            UPDATE nexent.evolution_confirmation_lock_t SET budget_stopped=TRUE WHERE lock_id=:id
        """), {"id": confirmation_lock})


def _active_confirmation(session, params):
    return session.execute(text("""
        SELECT NULL AS experiment_id, l.lock_id AS confirmation_lock_id, NULL AS review_turn_id,
               l.model_metering AS limits
        FROM nexent.evolution_generation_attempt_t a
        JOIN nexent.evolution_confirmation_lock_t l ON l.lock_id=a.confirmation_lock_id
        JOIN nexent.evolution_experiment_t e ON e.experiment_id=l.experiment_id
        JOIN nexent.evolution_confirmation_candidate_t c ON c.experiment_id=e.experiment_id
        JOIN nexent.evolution_confirmation_curator_t g ON (g.tenant_id,g.agent_id,g.user_id)
             =(e.tenant_id,e.agent_id,l.locked_by)
        JOIN nexent.user_tenant_t u ON (u.tenant_id,u.user_id)=(g.tenant_id,g.user_id)
        JOIN nexent.user_account_t account ON account.user_id=u.user_id
        WHERE a.attempt_id=:attempt AND a.tenant_id=:tenant AND a.created_by=:user
          AND a.metering_revision=:revision AND a.completed_at IS NULL AND NOT a.budget_stopped
          AND a.lease_until > clock_timestamp()
          AND e.tenant_id=:tenant AND c.submitted_by=:user AND NOT e.cancelled
          AND g.enabled AND g.update_time <= a.create_time
          AND u.delete_flag='N' AND account.delete_flag='N' AND cardinality(account.user_roles)>0
          AND EXISTS (SELECT 1 FROM nexent.user_tenant_t editor JOIN nexent.user_account_t editor_account USING (user_id)
                      WHERE editor.user_id=:user AND editor.tenant_id=:tenant AND editor.delete_flag='N'
                        AND editor_account.delete_flag='N')
          AND l.model_metering->>'revision'=:revision AND NOT l.budget_stopped
          AND NOT EXISTS (SELECT 1 FROM nexent.evolution_confirmation_result_t r WHERE r.lock_id=l.lock_id)
        FOR UPDATE OF a FOR SHARE OF l,e,c,g,u,account
    """), params).mappings().one_or_none()


def _active_diagnosis(session, params):
    job = session.execute(text("""
        SELECT NULL AS experiment_id, NULL AS confirmation_lock_id, r.turn_id AS review_turn_id,
               r.diagnosis_source_turn_id, NULL AS limits
        FROM nexent.evolution_generation_attempt_t a
        JOIN nexent.evolution_review_turn_t r ON r.turn_id=a.review_turn_id
        WHERE a.attempt_id=:attempt AND a.tenant_id=:tenant AND a.created_by=:user AND a.model_id=:model
          AND a.metering_revision=:revision AND a.completed_at IS NULL AND NOT a.budget_stopped
          AND a.lease_until > clock_timestamp() AND r.diagnosis_attempt_id=a.attempt_id
          AND r.diagnosis_claim_id IS NOT NULL AND r.diagnosis_lease_until > clock_timestamp()
          AND NOT EXISTS (SELECT 1 FROM nexent.evolution_model_charge_t c WHERE c.attempt_id=a.attempt_id)
        FOR UPDATE OF a,r
    """), params).mappings().one_or_none()
    if job is None:
        return None
    for turn in {job["review_turn_id"], job["diagnosis_source_turn_id"]} - {None}:
        if not authorized_review_turn(session, params["tenant"], params["user"], turn):
            return None
    return job


def reserve_model_call(tenant, user, model, attempt, allowance, tariff, output_tokens, *,
                       evaluation=False, confirmation=False, diagnosis=False):
    reserved_micros = cost_in_micros(tariff.max_input_tokens, output_tokens,
                                    tariff.input_micros_per_million, tariff.output_micros_per_million)
    params = dict(tenant=tenant, user=user, model=model, attempt=attempt, evaluation=evaluation and not confirmation,
                  confirmation=confirmation, diagnosis=diagnosis,
                  input=tariff.max_input_tokens, output=output_tokens, micros=reserved_micros,
                  input_rate=tariff.input_micros_per_million, output_rate=tariff.output_micros_per_million,
                  revision=allowance.revision())
    with get_db_session() as session:
        lock_model_charges(session, tenant)
        if diagnosis:
            active = _active_diagnosis(session, params)
        elif confirmation:
            active = _active_confirmation(session, params)
        else:
            active = session.execute(text("""
            SELECT a.experiment_id, a.confirmation_lock_id, a.review_turn_id, e.plan->'metering' AS limits
            FROM nexent.evolution_generation_attempt_t a
            LEFT JOIN nexent.evolution_experiment_t e ON e.experiment_id=a.experiment_id
            LEFT JOIN nexent.evolution_trial_t t ON t.trial_id=a.trial_id AND t.experiment_id=e.experiment_id
            WHERE a.attempt_id=:attempt AND a.tenant_id=:tenant AND a.created_by=:user
              AND a.metering_revision=:revision AND a.completed_at IS NULL AND NOT a.budget_stopped
              AND a.confirmation_lock_id IS NULL AND a.review_turn_id IS NULL
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
        experiment, confirmation_lock = active["experiment_id"], active["confirmation_lock_id"]
        params["experiment"] = experiment
        params["confirmation_lock"] = confirmation_lock
        params["review_turn"] = active["review_turn_id"]
        used_tokens, used_micros, exceeded = session.execute(text("""
            SELECT COALESCE(sum(COALESCE(reported_input + reported_output, reserved_input + reserved_output)), 0),
                   COALESCE(sum(COALESCE(reported_micros, reserved_micros)), 0),
                   COALESCE(bool_or(reported_input > reserved_input OR reported_output > reserved_output), false)
              FROM nexent.evolution_model_charge_t WHERE tenant_id=:tenant
               AND (experiment_id IS NOT NULL)=:evaluation
               AND (confirmation_lock_id IS NOT NULL)=:confirmation
               AND (review_turn_id IS NOT NULL)=:diagnosis
               AND create_time >= (date_trunc('day', clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')
        """), params).one()
        tokens = tariff.max_input_tokens + output_tokens
        daily_limit = exceeded or used_tokens + tokens > allowance.daily_tokens or used_micros + reserved_micros > allowance.daily_micros
        if daily_limit or active["limits"] and _exceeds_comparison(session, params, active["limits"], tokens):
            _stop_budget(session, attempt, experiment, confirmation_lock)
            return None
        return session.scalar(text("""
            INSERT INTO nexent.evolution_model_charge_t
                (tenant_id, attempt_id, experiment_id, confirmation_lock_id, review_turn_id, model_id,
                 reserved_input, reserved_output, reserved_micros,
                 input_rate, output_rate)
            VALUES (:tenant, :attempt, :experiment, :confirmation_lock, :review_turn, :model, :input, :output, :micros,
                    :input_rate, :output_rate)
            RETURNING charge_id
        """), params)


def _exceeds_comparison(session, params, limits, tokens):
    used_tokens, used_micros = session.execute(text("""
        SELECT COALESCE(sum(COALESCE(reported_input + reported_output, reserved_input + reserved_output)), 0),
               COALESCE(sum(COALESCE(reported_micros, reserved_micros)), 0)
          FROM nexent.evolution_model_charge_t WHERE tenant_id=:tenant
             AND (experiment_id=:experiment OR confirmation_lock_id=:confirmation_lock)
    """), params).one()
    return (used_tokens + tokens > limits["max_model_tokens"]
            or used_micros + params["micros"] > limits["max_model_micros"])


def reconcile_model_call(tenant, charge_id, input_tokens, output_tokens):
    with get_db_session() as session:
        lock_model_charges(session, tenant)
        params = dict(tenant=tenant, charge=charge_id, input=input_tokens, output=output_tokens)
        row = session.execute(text("""
            SELECT attempt_id, experiment_id, confirmation_lock_id, reserved_input, reserved_output, input_rate, output_rate
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
            _stop_budget(session, row["attempt_id"], row["experiment_id"], row["confirmation_lock_id"])
        return not exceeded
