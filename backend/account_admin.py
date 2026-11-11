# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Container-safe entry point independent of the image working directory."""

from infrastructure.security.account_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
