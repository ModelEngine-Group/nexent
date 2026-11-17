# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Construct parser and scoped storage in a child; retain job ownership in Management."""

from contracts.agentos_knowledge import ObjectReference
from contracts.knowledge_cleanse import parse_cleanse_request
from nexent.storage.errors import (
    CapabilityUnsupported,
    DeadlineExceeded,
    InvalidInput,
    OperationCancelled,
    OutcomeUnknown,
    Unavailable,
)

from infrastructure.file_processing.isolated import run_isolated


class ProcessCleanseExecutor:
    def __init__(self, factory, *, tick=None):
        if not callable(factory) or tick is not None and not callable(tick):
            raise InvalidInput()
        self.factory = factory
        self.tick = tick

    def __call__(self, row, request, *, context, on_finished=None):
        if parse_cleanse_request(row) != request:
            raise InvalidInput()

        def initialize(*, context):
            executor = self.factory(context=context)
            try:
                executor.warmup(context=context)
            except BaseException:
                executor.close()
                raise

            def execute(snapshot, *, context):
                try:
                    typed = parse_cleanse_request(snapshot)
                    return executor(snapshot, typed, context=context).model_dump(
                        mode="json"
                    )
                finally:
                    executor.close()

            return execute

        def tick(*, context):
            if self.tick is not None:
                self.tick(row, context=context)

        finished = False

        def confirm_finished():
            nonlocal finished
            if not finished:
                finished = True
                if on_finished is not None:
                    on_finished()

        try:
            result = run_isolated(
                initialize, row, context=context, tick=tick if self.tick else None,
                on_finished=confirm_finished,
            )
        except (CapabilityUnsupported, DeadlineExceeded, InvalidInput, OperationCancelled, Unavailable):
            # These categories cannot escape a dispatched process without reclamation.
            confirm_finished()
            raise
        try:
            return ObjectReference.model_validate(result)
        except ValueError:
            raise OutcomeUnknown(operation_id=context.operation_id) from None
