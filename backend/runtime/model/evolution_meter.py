# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime-side quota callback for candidate model requests."""

from contextlib import contextmanager

from contracts.evolution_metering import confirmation_budget, evaluation_budget, generation_budget
from infrastructure.rdb.evolution_model_charges import reconcile_model_call, reserve_model_call
from nexent.core.models.wire_budget import ModelWireBudgetExceeded, model_wire_budget


def meter_generation(attempt, model, actor):
    return _meter(attempt, model, actor, evaluation=False)


def meter_evaluation(attempt, actor, model=None, *, confirmation=False):
    return _meter(attempt, model, actor, evaluation=True, confirmation=confirmation)


@contextmanager
def _meter(attempt, model, actor, *, evaluation, confirmation=False):
    if attempt is None:
        yield
        return
    budget = confirmation_budget if confirmation else evaluation_budget if evaluation else generation_budget
    allowance = budget(actor.tenant_id)
    denied = False

    def admit(wire, wire_model_id=None):
        nonlocal denied
        if denied:
            raise ModelWireBudgetExceeded("Model budget stopped this request")
        actual_model = wire_model_id or model
        tariff = allowance.models.get(str(actual_model)) if allowance else None
        if tariff is None or model is not None and actual_model != model:
            denied = True
            raise ModelWireBudgetExceeded("No billing ceiling for the selected model")
        # Reject ambiguous billable multiplicities and output caps that could shadow the wire field.
        extra = wire.get("extra_body") or {}
        cap_keys = ("max_tokens", "max_completion_tokens")
        supplied = [key for key in cap_keys if key in wire]
        if (extra.get("n", wire.get("n", 1)) != 1 or len(supplied) > 1
                or any(key in extra for key in (*cap_keys, "max_output_tokens"))
                or "max_output_tokens" in wire):
            denied = True
            raise ModelWireBudgetExceeded("Cannot verify this model's output billing limit")
        cap_key = supplied[0] if supplied else "max_tokens"
        configured = wire.get(cap_key)
        output = min(configured, tariff.max_output_tokens) if type(configured) is int and configured > 0 else tariff.max_output_tokens
        wire[cap_key] = output
        charge = reserve_model_call(
            actor.tenant_id, actor.user_id, actual_model, attempt, allowance, tariff, output,
            evaluation=evaluation, confirmation=confirmation,
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
