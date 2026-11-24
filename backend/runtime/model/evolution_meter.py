# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime-side quota callback for candidate model requests."""

from contextlib import contextmanager

from contracts.evolution_metering import confirmation_budget, diagnosis_budget, evaluation_budget, generation_budget
from infrastructure.rdb.evolution_model_charges import reconcile_model_call, reserve_model_call
from nexent.core.models.wire_budget import ModelWireBudgetExceeded, model_wire_budget


def meter_generation(attempt, model, actor):
    return _meter(attempt, model, actor, evaluation=False)


def meter_evaluation(attempt, actor, model=None, *, confirmation=False):
    return _meter(attempt, model, actor, evaluation=True, confirmation=confirmation)


def meter_diagnosis(attempt, actor, model):
    return _meter(attempt, model, actor, evaluation=False, diagnosis=True)


def _apply_output_limit(wire, limit):
    # Reject ambiguous billable multiplicities and fields that could shadow the wire limit.
    extra = wire.get("extra_body") or {}
    cap_keys = ("max_tokens", "max_completion_tokens")
    supplied = [key for key in cap_keys if key in wire]
    if (extra.get("n", wire.get("n", 1)) != 1 or len(supplied) > 1
            or any(key in extra for key in (*cap_keys, "max_output_tokens"))
            or "max_output_tokens" in wire):
        raise ModelWireBudgetExceeded("Cannot verify this model's output limit")
    cap_key = supplied[0] if supplied else "max_tokens"
    configured = wire.get(cap_key)
    output = min(configured, limit) if type(configured) is int and configured > 0 else limit
    wire[cap_key] = output
    return output


@contextmanager
def limit_output_tokens(limit):
    """Apply a trusted job limit to each physical request, before quota reservation."""
    if limit is None:
        yield
        return
    meter = model_wire_budget.get()

    def admit(wire, model_id=None):
        _apply_output_limit(wire, limit)
        return meter(wire, model_id) if meter is not None else None

    context = model_wire_budget.set(admit)
    try:
        yield
    finally:
        model_wire_budget.reset(context)


@contextmanager
def _meter(attempt, model, actor, *, evaluation, confirmation=False, diagnosis=False):
    if attempt is None:
        yield
        return
    budget = (diagnosis_budget if diagnosis else confirmation_budget if confirmation
              else evaluation_budget if evaluation else generation_budget)
    allowance = budget(actor.tenant_id)
    denied = False

    def admit(wire, wire_model_id=None):
        nonlocal denied
        if denied:
            raise ModelWireBudgetExceeded("Model budget stopped this request")
        actual_model = wire_model_id or model
        tariff = (allowance.models.get(str(actual_model))
                  if allowance and (not diagnosis or allowance.model_id == actual_model) else None)
        if tariff is None or model is not None and actual_model != model:
            denied = True
            raise ModelWireBudgetExceeded("No billing ceiling for the selected model")
        try:
            output = _apply_output_limit(wire, tariff.max_output_tokens)
        except ModelWireBudgetExceeded:
            denied = True
            raise
        charge = reserve_model_call(
            actor.tenant_id, actor.user_id, actual_model, attempt, allowance, tariff, output,
            evaluation=evaluation, confirmation=confirmation, diagnosis=diagnosis,
        )
        if charge is None:
            denied = True
            raise ModelWireBudgetExceeded("Model token or cost budget exhausted")

        def settle(input_tokens, output_tokens):
            nonlocal denied
            if (type(input_tokens) is int and type(output_tokens) is int
                    and 0 <= input_tokens <= 10**12 and 0 <= output_tokens <= 10**12
                    and not reconcile_model_call(actor.tenant_id, charge, input_tokens, output_tokens)):
                denied = True
                raise ModelWireBudgetExceeded("Provider usage exceeds its declared billing limit")

        return settle

    context = model_wire_budget.set(admit)
    try:
        yield
        if denied:
            raise ModelWireBudgetExceeded("Model budget stopped this request")
    finally:
        model_wire_budget.reset(context)
