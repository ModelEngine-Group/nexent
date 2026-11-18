# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Provider-independent failures with safe messages and operation correlation."""


class StorageError(Exception):
    message = "Storage operation failed"

    def __init__(self, *, operation_id: str | None = None):
        super().__init__(self.message)
        self.operation_id = operation_id


class NotFound(StorageError):
    message = "Storage resource was not found"


class Conflict(StorageError):
    message = "Storage revision conflicts with the requested operation"


class InvalidInput(StorageError):
    message = "Invalid storage operation input"


class ScopeDenied(StorageError):
    message = "Storage operation is outside the authorized scope"


class CapabilityUnsupported(StorageError):
    message = "The storage binding lacks a required capability"


class Unavailable(StorageError):
    message = "Storage is unavailable"


class DeadlineExceeded(StorageError):
    message = "Storage operation deadline exceeded"


class OperationCancelled(StorageError):
    message = "Storage operation was cancelled"


class OutcomeUnknown(StorageError):
    message = "Storage write outcome is unknown; reconcile before retrying"


class PartialFailure(StorageError):
    message = "Some storage operations were not confirmed"

    def __init__(self, *, results: tuple, operation_id: str | None = None):
        super().__init__(operation_id=operation_id)
        self.results = tuple(results)
