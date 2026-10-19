"""Provision legacy LLMs explicitly after applying the runtime outlet schema migration."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))


def main():
    from database.model_runtime_profile_db import provision_runtime_outlet_batch
    from services.model_runtime_provisioning_service import (
        build_runtime_outlet_snapshot,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist snapshots; default is a dry run")
    parser.add_argument("--tenant-id")
    args = parser.parse_args()
    cursor, counts = 0, {"migrated": 0, "ready": 0, "failed": 0}
    while True:
        batch = provision_runtime_outlet_batch(build_runtime_outlet_snapshot, after_model_id=cursor,
            tenant_id=args.tenant_id, dry_run=not args.apply)
        if not batch:
            break
        for item in batch:
            counts[item["status"]] += 1
        cursor = batch[-1]["model_id"]
    print(json.dumps({"dry_run": not args.apply, **counts}))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
