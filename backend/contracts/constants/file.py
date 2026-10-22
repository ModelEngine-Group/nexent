# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


# Upload Configuration
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
MAX_CONCURRENT_UPLOADS = 5


# Preview Configuration
FILE_PREVIEW_SIZE_LIMIT = 100 * 1024 * 1024  # 100MB
# Limit concurrent Office-to-PDF conversions
MAX_CONCURRENT_CONVERSIONS = 5
# Supported Office file MIME types
OFFICE_MIME_TYPES = [
    "application/msword",  # .doc
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.ms-excel",  # .xls
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "application/vnd.ms-powerpoint",  # .ppt
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
]
