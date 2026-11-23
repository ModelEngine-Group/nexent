"""Batch-unique resource identifiers verified absent from PostgreSQL."""

from __future__ import annotations

import hashlib
import os
import threading

from shared.postgres import postgres_sql


_LOCK = threading.Lock()
_ALLOCATED: dict[str, int] = {}


def _candidate(namespace: str, attempt: int) -> int:
    batch = os.environ.get("TEST_BATCH") or os.environ.get("GITHUB_RUN_ID") or "manual"
    digest = hashlib.sha256(f"{batch}:{namespace}:{attempt}".encode()).digest()
    # Stay inside signed int32 while avoiding conventional fixtures and small
    # sequence values. Different batches and namespaces produce different IDs.
    return 1_000_000_000 + int.from_bytes(digest[:4], "big") % 1_000_000_000


def _assert_absent_everywhere(candidate: int) -> None:
    # Check every integer identifier-like column in application schemas in one
    # server-side block. Identifiers come from PostgreSQL metadata and are
    # quoted with format(%I), so no test-controlled identifier is interpolated.
    postgres_sql(f"""
DO $nexent_absent_id$
DECLARE
  column_record record;
  occupied boolean;
BEGIN
  FOR column_record IN
    SELECT table_schema, table_name, column_name
      FROM information_schema.columns
     WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
       AND data_type IN ('smallint', 'integer', 'bigint')
       AND (column_name = 'id' OR column_name LIKE '%\\_id' ESCAPE '\\')
  LOOP
    EXECUTE format(
      'SELECT EXISTS (SELECT 1 FROM %I.%I WHERE %I = $1)',
      column_record.table_schema, column_record.table_name, column_record.column_name
    ) INTO occupied USING {candidate};
    IF occupied THEN
      RAISE EXCEPTION 'candidate identifier is occupied';
    END IF;
  END LOOP;
END
$nexent_absent_id$;
""", expected_error_marker="candidate identifier is occupied")


def absent_numeric_id(namespace: str = "generic") -> int:
    """Return a stable-for-process, batch-unique ID proven absent in the DB."""
    with _LOCK:
        if namespace in _ALLOCATED:
            return _ALLOCATED[namespace]
        for attempt in range(20):
            candidate = _candidate(namespace, attempt)
            try:
                _assert_absent_everywhere(candidate)
            except Exception as exc:
                if "candidate identifier is occupied" in str(exc):
                    continue
                raise
            if candidate not in _ALLOCATED.values():
                _ALLOCATED[namespace] = candidate
                return candidate
    raise RuntimeError(f"could not allocate absent numeric ID for {namespace}")
