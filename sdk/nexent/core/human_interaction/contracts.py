"""Control signals are not tool errors and must cross exception wrappers intact."""

from typing import Any, Protocol


class AttemptSuspended(BaseException):
    """The attempt durably yielded because live continuation is unavailable."""


class RunTerminated(BaseException):
    """The run was terminated or this attempt no longer owns its execution lease."""


class StepSteered(BaseException):
    """The current code suffix was abandoned after in-loop user steering."""


class RecoveryRequired(BaseException):
    """Execution certainty or checkpoint compatibility requires reconciliation."""


class InteractionPort(Protocol):
    """All writes are fenced and scoped by the application-provided implementation."""

    run_id: str
    checkpoint: dict | None

    def save_checkpoint(self, checkpoint: dict) -> None: ...

    def bind_executor(self, identity: dict) -> None: ...

    def boundary(self, checkpoint: dict) -> dict | None: ...

    def dispatch(self, slot: str, tool: str, arguments: dict, *, interaction: dict | None = None) -> dict: ...

    def receipt(self, slot: str, result: Any, *, uncertain: bool = False) -> None: ...

    def save_plan(self, plan: dict) -> None: ...

    def load_plan(self) -> dict | None: ...
