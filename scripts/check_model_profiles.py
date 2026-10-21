# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Check packaged model profiles before submission, without starting application services."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk"))

from nexent.core.model_service.profiles.submission import check_profile_catalog


def main():
    try:
        catalog = check_profile_catalog()
    except ValueError as error:
        # SourceReadError contains identifiers only; never print source values.
        category = getattr(error, "category", "PROFILE_CONFIGURATION_INVALID")
        print(f"{category}: {getattr(error, 'file_path', '')}: {getattr(error, 'source_path', '')}", file=sys.stderr)
        return 1
    print(f"Model profile submission checks passed: {catalog.revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
