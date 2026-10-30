# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Start only an existing local source database and discover its published port."""

import json
import subprocess
import sys

from deploy.sql.tools.supabase_to_postgres.settings import MigrationSetupError


def _docker(*args):
    try:
        result = subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise MigrationSetupError(
            "Docker is unavailable; start the source database or configure SUPABASE_POSTGRES_HOST/PORT"
        ) from None
    if result.returncode:
        raise MigrationSetupError(
            "Docker source database operation failed; check Docker and the existing container"
        )
    return result.stdout


def prepare_source(params, container=None, *, allow_start=True):
    if not container:
        names = _docker("ps", "-a", "--format", "{{.Names}}").splitlines()
        candidates = [name for name in names if "supabase" in name.lower() and "db" in name.lower()]
        if len(candidates) != 1:
            raise MigrationSetupError(
                "Cannot identify one existing Supabase database container; use --source-container "
                "or configure SUPABASE_POSTGRES_HOST/PORT. No empty database will be created"
            )
        container = candidates[0]
    template = ('{"running":{{json .State.Running}},'
                '"ports":{{json .NetworkSettings.Ports}},"bindings":{{json .HostConfig.PortBindings}}}')
    try:
        state = json.loads(_docker("inspect", "--format", template, container))
    except (TypeError, ValueError):
        raise MigrationSetupError("Cannot read source container state") from None
    if not state.get("running"):
        if not allow_start:
            raise MigrationSetupError("Source container is stopped; start it or remove --no-start-source")
        _docker("start", container)
        try:
            state = json.loads(_docker("inspect", "--format", template, container))
        except (TypeError, ValueError):
            raise MigrationSetupError("Cannot read source container published port") from None
        print("Started the existing Supabase database container; waiting for PostgreSQL.", file=sys.stderr)
    ports = state.get("ports") or state.get("bindings") or {}
    key = str(params["port"]) + "/tcp"
    if key not in ports:
        key = "5432/tcp" if "5432/tcp" in ports else next(iter(ports), "")
    bindings = ports.get(key) or []
    if not bindings or not bindings[0].get("HostPort"):
        raise MigrationSetupError(
            "Source container has no published PostgreSQL port; configure a reachable SUPABASE_POSTGRES_HOST/PORT"
        )
    binding = next((item for item in bindings if item.get("HostIp") != "::"), bindings[0])
    host = binding.get("HostIp") or "127.0.0.1"
    params["host"] = "127.0.0.1" if host == "0.0.0.0" else "::1" if host == "::" else host
    params["port"] = int(binding["HostPort"])
    return container


def source_stack_configuration(values, container):
    """Resolve only the selected local source and configured legacy peers."""
    from deploy.sql.tools.supabase_to_postgres.legacy_stack import configuration

    return configuration({**values, "SUPABASE_MIGRATION_DB_CONTAINER": container})[0]


def cleanup_source_stack(values):
    """Remove source DB/Auth/Kong containers without deleting persistent volumes."""
    from deploy.sql.tools.supabase_to_postgres.legacy_stack import execute

    execute("down", values)
