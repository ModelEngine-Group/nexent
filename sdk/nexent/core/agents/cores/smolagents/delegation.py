# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Validate CodeAgent actions against the common delegation state."""

from nexent.core.agents.orchestration.delegation import DelegationError
from nexent.core.agents.orchestration.delegation import DelegationPolicy as SharedDelegationPolicy
from nexent.core.agents.output.python_actions import (
    is_delegation_action,
    is_parent_preparation_action,
    parallel_delegation_targets,
)


class DelegationPolicy(SharedDelegationPolicy):
    """Project a Python action into the shared authorized-target contract."""

    def __init__(self, query, collaborators, *, enabled=True, parallel_executor_available=True):
        super().__init__(query, collaborators, enabled=enabled, allow_parent_preparation=True)
        self.parallel_executor_available = parallel_executor_available
        self.parallel_required = self.parallel_requested and len(self.names) > 1
        self.completed = set()

    @property
    def instruction(self):
        if not self.pending or (self.parent_preparation and not self.parent_prepared):
            return super().instruction
        remaining = sorted(self.names - self.completed)
        if self.parallel_required and len(remaining) > 1:
            tasks = ", ".join(f'({name}, {{"task": "Describe this worker\'s task"}})' for name in remaining)
            return (
                "The current request requires one parallel batch of the named collaborators. "
                f"Use one code action: results = parallel_executor(tasks=[{tasks}]). "
                "Pass each worker its own concrete task. Wait for all actual results before answering."
            )
        if self.parallel_required:
            return (
                f"Call only the unfinished collaborator {remaining[0]} directly. "
                "Keep the successful result already returned by the other collaborator. "
                "Report actual execution and any failures truthfully."
            )
        return super().instruction

    def record_dispatch(self, name):
        if not self.parallel_required:
            super().record_dispatch(name)
        elif name in self.names:
            self.completed.add(name)
            if self.names <= self.completed:
                self.dispatched = True

    def validate_code(self, code):
        """Validate the proposal and indicate whether it is the initial parent action."""
        if not self.pending:
            return False
        if self.parent_preparation and not self.parent_prepared:
            if self.names and is_parent_preparation_action(code, self.collaborator_names):
                return True
            self.validate_targets([])
        remaining = self.names - self.completed
        if self.parallel_executor_available:
            targets = set(parallel_delegation_targets(code, self.collaborator_names))
            if targets and targets <= remaining and (not self.parallel_required or targets == remaining):
                return False
        if self.parallel_required and len(remaining) != 1:
            raise DelegationError("DELEGATION_REQUIRED")
        self.validate_targets(
            [next(iter(remaining), "")] if is_delegation_action(code, remaining) else []
        )
        return False

    def record_parent_preparation(self):
        """Advance only after the parent action ran successfully."""
        self.parent_prepared = True
