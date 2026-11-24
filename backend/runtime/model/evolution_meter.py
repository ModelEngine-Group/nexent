# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime-side quota callback for candidate model requests."""

from contextlib import contextmanager

from contracts.evolution_metering import generation_budget
from infrastructure.rdb.evolution_model_charges import reconcile_model_call, reserve_model_call
from nexent.core.models.wire_budget import ModelWireBudgetExceeded, model_wire_budget


@contextmanager
def meter_generation(attempt, model, actor):
    if attempt is None:
        yield
        return
    allowance = generation_budget(actor.tenant_id)
    tariff = allowance.models.get(str(model)) if allowance else None
    if tariff is None:
        raise ModelWireBudgetExceeded("No billing ceiling for the selected generation model")

    def admit(wire):
        # Reject ambiguous billable multiplicities and output caps that could shadow the wire field.
        extra = wire.get("extra_body") or {}
        cap_keys = ("max_tokens", "max_completion_tokens")
        supplied = [key for key in cap_keys if key in wire]
        if (extra.get("n", wire.get("n", 1)) != 1 or len(supplied) > 1
                or any(key in extra for key in (*cap_keys, "max_output_tokens"))
                or "max_output_tokens" in wire):
            raise ModelWireBudgetExceeded("Cannot verify this model's output billing limit")
        cap_key = supplied[0] if supplied else "max_tokens"
        configured = wire.get(cap_key)
        output = min(configured, tariff.max_output_tokens) if type(configured) is int and configured > 0 else tariff.max_output_tokens
        wire[cap_key] = output
        charge = reserve_model_call(actor.tenant_id, actor.user_id, model, attempt, allowance, tariff, output)
        if charge is None:
            raise ModelWireBudgetExceeded("Generation token or cost budget exhausted")

        def settle(input_tokens, output_tokens):
            if (type(input_tokens) is int and type(output_tokens) is int
                    and 0 <= input_tokens <= 10**12 and 0 <= output_tokens <= 10**12
                    and not reconcile_model_call(actor.tenant_id, charge, input_tokens, output_tokens)):
                raise ModelWireBudgetExceeded("Provider usage exceeds its declared billing limit")

        return settle

    context = model_wire_budget.set(admit)
    try:
        yield
    finally:
        model_wire_budget.reset(context)
