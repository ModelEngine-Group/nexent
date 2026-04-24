#!/usr/bin/env python3
"""Seed builtin prompt templates from YAML files into PostgreSQL.

This script is idempotent and safe to run multiple times.
It inserts/updates builtin template rows for tenants from user_tenant_t.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import List

import psycopg2


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE_NAME = "prompt_generate"
DEFAULT_TEMPLATE_TYPE = "prompt_generate"
DEFAULT_DESCRIPTION = "Default prompt generation template"


def _resolve_template_file(filename: str) -> Path:
    """Resolve template file path with fallback candidates."""
    candidates = [
        Path("/opt/backend/prompts/utils") / filename,
        Path("backend/prompts/utils") / filename,
        Path(__file__).resolve().parents[2] / "backend" / "prompts" / "utils" / filename,
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"Template file not found: {filename}, checked: {candidates}")


def _read_template_text(filename: str) -> str:
    path = _resolve_template_file(filename)
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"Template file is empty: {path}")
    return content


def _get_connection_params() -> dict:
    return {
        "host": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "port": os.getenv("POSTGRES_PORT", "5434"),
        "dbname": os.getenv("POSTGRES_DB", "nexent"),
        "user": os.getenv("POSTGRES_USER", "nexent"),
        "password": os.getenv("NEXENT_POSTGRES_PASSWORD", ""),
    }


def _fetch_tenant_ids(conn, tenant_id: str | None = None) -> List[str]:
    with conn.cursor() as cursor:
        if tenant_id:
            cursor.execute(
                """
                SELECT DISTINCT tenant_id
                FROM nexent.user_tenant_t
                WHERE tenant_id = %s
                  AND delete_flag = 'N'
                """,
                (tenant_id,),
            )
        else:
            cursor.execute(
                """
                SELECT DISTINCT tenant_id
                FROM nexent.user_tenant_t
                WHERE tenant_id IS NOT NULL
                  AND tenant_id <> ''
                  AND delete_flag = 'N'
                ORDER BY tenant_id
                """
            )
        rows = cursor.fetchall()
    return [row[0] for row in rows if row and row[0]]


def _check_table_exists(conn) -> bool:
    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass('nexent.ag_prompt_template_t')")
        table_name = cursor.fetchone()[0]
    return table_name is not None


def _upsert_template(conn, tenant_id: str, content_zh: str, content_en: str, dry_run: bool) -> bool:
    if dry_run:
        logger.info("[DRY-RUN] Would seed template for tenant_id=%s", tenant_id)
        return True

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO nexent.ag_prompt_template_t (
                tenant_id,
                template_name,
                description,
                template_type,
                content_zh,
                content_en,
                source,
                created_by,
                updated_by
            ) VALUES (%s, %s, %s, %s, %s, %s, 'builtin', 'system', 'system')
            ON CONFLICT (tenant_id, template_name)
            DO UPDATE SET
                description = EXCLUDED.description,
                template_type = EXCLUDED.template_type,
                content_zh = EXCLUDED.content_zh,
                content_en = EXCLUDED.content_en,
                source = 'builtin',
                updated_by = 'system',
                update_time = CURRENT_TIMESTAMP
            WHERE nexent.ag_prompt_template_t.source = 'builtin'
            """,
            (
                tenant_id,
                DEFAULT_TEMPLATE_NAME,
                DEFAULT_DESCRIPTION,
                DEFAULT_TEMPLATE_TYPE,
                content_zh,
                content_en,
            ),
        )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed builtin prompt templates from YAML files")
    parser.add_argument("--tenant-id", help="Seed one specific tenant only", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    try:
        content_zh = _read_template_text("prompt_generate_zh.yaml")
        content_en = _read_template_text("prompt_generate_en.yaml")
    except Exception as exc:
        logger.error("Failed to read template YAML files: %s", exc)
        return 1

    conn = None
    try:
        conn = psycopg2.connect(**_get_connection_params())
        conn.autocommit = False

        if not _check_table_exists(conn):
            logger.warning("Table nexent.ag_prompt_template_t does not exist. Skip seeding.")
            return 0

        tenant_ids = _fetch_tenant_ids(conn, tenant_id=args.tenant_id)
        if not tenant_ids:
            logger.info("No tenant found. Nothing to seed.")
            return 0

        logger.info("Start seeding builtin prompt template for %d tenant(s)", len(tenant_ids))
        success = 0
        for tenant_id in tenant_ids:
            if _upsert_template(conn, tenant_id, content_zh, content_en, args.dry_run):
                success += 1

        if args.dry_run:
            conn.rollback()
            logger.info("Dry run finished. %d/%d tenant(s) would be processed.", success, len(tenant_ids))
        else:
            conn.commit()
            logger.info("Seeding finished. %d/%d tenant(s) processed.", success, len(tenant_ids))
        return 0
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        logger.error("Failed to seed prompt templates: %s", exc)
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
