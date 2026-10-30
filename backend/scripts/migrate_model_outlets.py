# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Preview or apply the one-time LLM outlet migration with sanitized summaries."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist snapshots; default is a read-only preview")
    parser.add_argument("--batch-size", type=int, default=100)
    arguments = parser.parse_args()
    from management.services.model.outlet_migration import migrate_legacy_outlets

    report = migrate_legacy_outlets(dry_run=not arguments.apply, batch_size=arguments.batch_size)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
