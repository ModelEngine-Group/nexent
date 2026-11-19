# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Safe trajectory domain failures shared by persistence, services and HTTP."""


class QueryError(Exception):
    def __init__(self, code: str, status: int = 422, *, retry_after: int | None = None):
        self.code, self.status, self.retry_after = code, status, retry_after
        super().__init__(code)
