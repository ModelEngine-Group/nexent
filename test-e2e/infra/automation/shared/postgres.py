"""One PostgreSQL execution contract shared by D1, D2, D3 and D5.

The fixed suite runs beside the deployed Nexent containers.  SQL therefore
executes through the PostgreSQL container instead of assuming that port 5432
is published on localhost.  Connection identity is discovered from the
container's own POSTGRES_* environment and no password is copied into logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import subprocess
from functools import lru_cache
from contextvars import ContextVar
from urllib.parse import quote_plus

from shared.asset_registry import AssetDependencyError, AutomationInfrastructureError

# Only explicit isolated fixtures set this; parallel asyncio contexts cannot
# redirect one another's database. Administrative operations pass database=.
_isolated_database = ContextVar('nexent_test_isolated_database', default=None)


@dataclass(frozen=True)
class PostgresTarget:
    container: str
    user: str
    database: str
    password: str = field(repr=False)
    host: str
    port: int = 5432


def postgres_connect_kwargs() -> dict:
    """Driver keyword mapping only; does not create or reset a database."""
    target = postgres_target()
    return {
        'host': target.host, 'port': target.port, 'user': target.user,
        'password': target.password, 'dbname': _isolated_database.get() or target.database,
    }


def _run(command: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AutomationInfrastructureError(f"PostgreSQL container command failed: {exc}") from exc


@lru_cache(maxsize=1)
def postgres_target() -> PostgresTarget:
    container = os.environ.get("NEXENT_TEST_POSTGRES_CONTAINER", "nexent-postgresql")
    inspected = _run([
        "docker", "inspect", container,
        "--format", "{{range .Config.Env}}{{println .}}{{end}}",
    ])
    if inspected.returncode != 0:
        raise AssetDependencyError(
            "services", "postgres", dependency_case_id="D0-POSTGRES",
            detail=f"cannot inspect PostgreSQL container {container}: {inspected.stderr.strip()}",
        )
    values: dict[str, str] = {}
    for raw in inspected.stdout.splitlines():
        if "=" in raw:
            key, value = raw.split("=", 1)
            values[key] = value
    user = os.environ.get("NEXENT_TEST_PG_USER") or values.get("POSTGRES_USER")
    database = os.environ.get("NEXENT_TEST_PG_DB") or values.get("POSTGRES_DB")
    password = os.environ.get("NEXENT_TEST_PG_PASSWORD") or values.get("POSTGRES_PASSWORD")
    address = _run(["docker", "inspect", container, "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"])
    host = os.environ.get("NEXENT_TEST_PG_HOST") or address.stdout.strip()
    if not user or not database or not password or not host:
        raise AssetDependencyError(
            "services", "postgres", dependency_case_id="D0-POSTGRES",
            detail=f"cannot resolve complete PostgreSQL target from container {container}",
        )
    # On Docker Desktop hosts (Windows/macOS) the container-internal IP is not
    # reachable from the host; tests must connect through the published port.
    port_env = os.environ.get("NEXENT_TEST_PG_PORT", "").strip()
    port = int(port_env) if port_env.isdigit() else 5432
    return PostgresTarget(container=container, user=user, database=database, password=password, host=host, port=port)


def postgres_url(*, database: str | None = None) -> str:
    """Return an in-memory DSN for libraries that must exercise PostgreSQL types."""
    target = postgres_target()
    return (
        f"postgresql+psycopg2://{quote_plus(target.user)}:{quote_plus(target.password)}"
        f"@{target.host}:{target.port}/{quote_plus(database or _isolated_database.get() or target.database)}"
    )


def apply_product_postgres_env() -> PostgresTarget:
    """Populate the environment consumed by Nexent's database modules.

    Call this before importing ``consts.const`` or ``database.client`` because
    those product modules resolve their connection constants at import time.
    """
    target = postgres_target()
    os.environ.update({
        "POSTGRES_HOST": target.host,
        "POSTGRES_PORT": str(target.port),
        "POSTGRES_USER": target.user,
        "POSTGRES_DB": target.database,
        "NEXENT_POSTGRES_PASSWORD": target.password,
    })
    return target


def postgres_sql(sql: str, *, database: str | None = None, tuples_only: bool = True,
                 expected_error_marker: str | None = None) -> str:
    target = postgres_target()
    command = [
        "docker", "exec", "-i", target.container,
        "psql", "-X", "-v", "ON_ERROR_STOP=1",
        "-U", target.user, "-d", database or _isolated_database.get() or target.database,
    ]
    if tuples_only:
        command.extend(["-A", "-t", "-F", "\t"])
    result = _run(command, input_text=sql)
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "unknown psql error"
        # psql appends a PL/pgSQL CONTEXT line after the actual ERROR. Preserve
        # only an explicitly expected, non-sensitive marker for callers that
        # need to retry a deliberate sentinel exception.
        if expected_error_marker and expected_error_marker in result.stderr:
            detail = expected_error_marker
        raise AutomationInfrastructureError(f"PostgreSQL statement failed: {detail}")
    return result.stdout


def postgres_scalar(sql: str, *, database: str | None = None) -> str:
    rows = [line.strip() for line in postgres_sql(sql, database=database).splitlines() if line.strip()]
    if len(rows) != 1:
        raise AutomationInfrastructureError(f"expected one PostgreSQL scalar row, received {len(rows)}")
    return rows[0]
