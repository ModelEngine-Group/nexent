# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Validate CodeAgent actions against the common delegation state."""

from nexent.core.agents.orchestration.delegation import DelegationPolicy as SharedDelegationPolicy
from nexent.core.agents.output.python_actions import is_delegation_action


class DelegationPolicy(SharedDelegationPolicy):
    """Project a Python action into the shared authorized-target contract."""

    def validate_code(self, code, *, allow_parallel=False):
        if self.pending:
            self.validate_targets(
                [next(iter(self.names), "")] if is_delegation_action(code, self.names, allow_parallel=allow_parallel) else []
            )
