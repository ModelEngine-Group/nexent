# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run on the host to import historical authentication accounts into PostgreSQL."""

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from deploy.sql.tools.supabase_to_postgres.settings import MigrationSetupError, connections, load_settings
from deploy.sql.tools.supabase_to_postgres.source_container import prepare_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write after preflight; default is dry-run")
    parser.add_argument("--env-file", type=Path, default=ROOT / "deploy/env/.env")
    parser.add_argument("--source-container", help="Existing local Supabase database container name")
    parser.add_argument("--no-start-source", action="store_true", help="Fail if the local source container is stopped")
    parser.add_argument("--wait-timeout", type=int, default=30, help="Source readiness timeout in seconds")
    args = parser.parse_args()
    if args.wait_timeout < 1 or args.wait_timeout > 300:
        parser.error("--wait-timeout must be between 1 and 300")
    import psycopg2
    from deploy.sql.tools.supabase_to_postgres.migration import (
        MigrationConflict, read_source_users, import_users,
    )

    try:
        source_params, target_params, managed = connections(load_settings(args.env_file))
        if managed or args.source_container:
            prepare_source(source_params, args.source_container, allow_start=not args.no_start_source)
        deadline = time.monotonic() + args.wait_timeout
        while True:
            try:
                source = psycopg2.connect(**source_params)
                break
            except psycopg2.OperationalError:
                if not managed or time.monotonic() >= deadline:
                    raise MigrationSetupError(
                        "Cannot connect to source PostgreSQL; check its readiness, published port and source password"
                    ) from None
                time.sleep(1)
        try:
            with source:
                source.set_session(readonly=True, isolation_level="REPEATABLE READ")
                rows = read_source_users(source)
        finally:
            source.close()
        target = psycopg2.connect(**target_params)
        try:
            with target:
                result = import_users(target, rows, dry_run=not args.apply)
        finally:
            target.close()
        print(json.dumps(result))
        return 0
    except (MigrationConflict, MigrationSetupError) as exc:
        print("Account migration preflight rejected: " + str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print("Account migration failed (" + type(exc).__name__
              + "); inspect prerequisites and run preflight again.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
