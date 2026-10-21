# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


from typing import Optional


class UploadFilesResult(tuple):
    """Backward-compatible upload result with optional quota and lifecycle metadata."""

    quota_status: Optional[dict]
    file_records: list

    def __new__(
        cls,
        errors: list,
        uploaded_file_paths: list,
        uploaded_filenames: list,
        quota_status: Optional[dict] = None,
        file_records: Optional[list] = None,
    ):
        result = super().__new__(cls, (errors, uploaded_file_paths, uploaded_filenames))
        result.quota_status = quota_status
        result.file_records = file_records or []
        return result
