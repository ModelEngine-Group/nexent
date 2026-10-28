# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Host-side connection settings for the one-time migration tool."""

import getpass
import os
import sys

from dotenv import dotenv_values


class MigrationSetupError(ValueError):
    """Operator-actionable prerequisite error containing no credential values."""


def load_settings(env_file, environ=None):
    file_values = dotenv_values(env_file) if env_file.is_file() else {}
    return {**file_values, **(os.environ if environ is None else environ)}


def _port(value):
    try:
        result = int(value)
        if not 1 <= result <= 65535:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise MigrationSetupError("Database port must be between 1 and 65535") from None


def source_password(values):
    if values.get("SUPABASE_POSTGRES_PASSWORD"):
        return values["SUPABASE_POSTGRES_PASSWORD"]
    if not sys.stdin.isatty():
        raise MigrationSetupError(
            "Set SUPABASE_POSTGRES_PASSWORD before noninteractive migration"
        )
    value = getpass.getpass("Supabase PostgreSQL password: ")
    if not value:
        raise MigrationSetupError("Supabase PostgreSQL password is required")
    return value


def connections(values):
    """Use existing deployment settings and translate Docker-only hostnames."""
    host = values.get("SUPABASE_POSTGRES_HOST")
    service_host = host in {"supabase_db", "supabase-db-mini", "nexent-supabase-db"}
    source = {
        "host": "127.0.0.1" if not host or service_host else host,
        "port": _port(values.get("SUPABASE_POSTGRES_PORT") or 5436),
        "dbname": values.get("SUPABASE_POSTGRES_DB") or "supabase",
        "user": values.get("SUPABASE_POSTGRES_USER") or "postgres",
        "password": source_password(values),
        "connect_timeout": 3,
    }
    host = values.get("POSTGRES_HOST") or "127.0.0.1"
    internal = host == "nexent-postgresql"
    target = {
        "host": "127.0.0.1" if internal else host,
        "port": _port(5434 if internal else values.get("POSTGRES_PORT") or 5434),
        "user": values.get("POSTGRES_USER") or "root",
        "dbname": values.get("POSTGRES_DB") or "nexent",
        "password": values.get("NEXENT_POSTGRES_PASSWORD"),
        "connect_timeout": 3,
    }
    if not target["password"]:
        raise MigrationSetupError("Set NEXENT_POSTGRES_PASSWORD")
    # An explicitly reachable host uses that connection directly; service aliases
    # and defaults retain automatic local container discovery/startup.
    return source, target, service_host or not values.get("SUPABASE_POSTGRES_HOST")
