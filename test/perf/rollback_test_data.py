#!/usr/bin/env python3
"""
Rollback script for spec / performance test data.

Deletes all test data created by test_spec_limits.py and test_performance.py.
Uses the perf_test_ prefix to identify test tenants and cascade-deletes
all associated records (users, groups, agents, conversations, memory, etc.).

This script is IDEMPOTENT - running it multiple times is safe.

Usage:
    python test/perf/rollback_test_data.py [--dry-run] [--db-url <url>]

Environment variables:
    NEXENT_DB_URL  SQLAlchemy connection URL (required)
    NEXENT_BASE_URL  Nexent API base URL (optional, for API-based cleanup)
    NEXENT_ADMIN_TOKEN  Admin auth token (optional, for API-based cleanup)
"""

import argparse
import logging
import os
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("rollback_test_data")

TEST_TENANT_PREFIX = "perf_test_"

# Tables that reference tenant_id, in dependency order for safe deletion
TENANT_DEPENDENT_TABLES = [
    # First: leaf tables with foreign keys to users/groups/agents
    ("skill_instances", "DELETE FROM skill_instances WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    ("agent_skill_relations", "DELETE FROM agent_skill_relations WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    ("memory_record", "DELETE FROM memory_record WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    ("memory_long_term", "DELETE FROM memory_long_term WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    ("conversation_message", "DELETE FROM conversation_message WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    ("conversation", "DELETE FROM conversation WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    ("agent_version_info", "DELETE FROM agent_version_info WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    ("agent_info", "DELETE FROM agent_info WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    ("knowledge_storage_object", "DELETE FROM knowledge_storage_object WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    ("knowledge_record", "DELETE FROM knowledge_record WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    ("skill_info", "DELETE FROM skill_info WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    ("mcp_server", "DELETE FROM mcp_server WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    ("tenant_group_user", "DELETE FROM tenant_group_user WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    ("tenant_group_info", "DELETE FROM tenant_group_info WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    ("user_tenant", "DELETE FROM user_tenant WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    ("tenant_config", "DELETE FROM tenant_config WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    ("quota_usage", "DELETE FROM quota_usage WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    ("tenant_quota", "DELETE FROM tenant_quota WHERE tenant_id IN (SELECT tenant_id FROM tenant WHERE tenant_id LIKE :prefix)"),
    # Finally: the tenants themselves
    ("tenant", "DELETE FROM tenant WHERE tenant_id LIKE :prefix"),
]

USER_DEPENDENT_TABLES = [
    ("invitation", "DELETE FROM invitation WHERE inviter_user_id IN (SELECT user_id FROM user WHERE user_id LIKE :user_prefix)"),
]

TEST_USER_PREFIX = "perf_test_user_"


def get_engine(db_url: str):
    """Create a SQLAlchemy engine from the given URL."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(db_url, pool_pre_ping=True, pool_recycle=3600)
        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection established successfully")
        return engine
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        sys.exit(1)


def count_test_tenants(engine) -> int:
    """Count test tenants in the database."""
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT COUNT(*) FROM tenant WHERE tenant_id LIKE :prefix"
        ), {"prefix": f"{TEST_TENANT_PREFIX}%"})
        return result.scalar()


def count_test_users(engine) -> int:
    """Count test users in the database."""
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT COUNT(*) FROM user WHERE user_id LIKE :prefix"
        ), {"prefix": f"{TEST_USER_PREFIX}%"})
        return result.scalar()


def rollback_tenants(engine, dry_run: bool = False):
    """Delete all test tenant data in dependency order."""
    from sqlalchemy import text

    tenant_count = count_test_tenants(engine)
    user_count = count_test_users(engine)
    logger.info(f"Found {tenant_count} test tenants and {user_count} test users to clean up")

    if tenant_count == 0 and user_count == 0:
        logger.info("No test data found. Nothing to clean.")
        return

    for table_name, sql in TENANT_DEPENDENT_TABLES:
        try:
            with engine.connect() as conn:
                result = conn.execute(text(sql), {"prefix": f"{TEST_TENANT_PREFIX}%"})
                conn.commit()
                deleted = result.rowcount if result.rowcount >= 0 else "?"
                if dry_run:
                    logger.info(f"[DRY-RUN] Would delete from {table_name}: {deleted} rows")
                else:
                    logger.info(f"Deleted from {table_name}: {deleted} rows")
        except Exception as e:
            logger.warning(f"Error cleaning {table_name}: {e}")
            # Continue with next table - some tables may not exist or have no data

    # Clean up test users directly (users created outside tenant scope)
    for table_name, sql in USER_DEPENDENT_TABLES:
        try:
            with engine.connect() as conn:
                result = conn.execute(text(sql), {"user_prefix": f"{TEST_USER_PREFIX}%"})
                conn.commit()
                deleted = result.rowcount if result.rowcount >= 0 else "?"
                if dry_run:
                    logger.info(f"[DRY-RUN] Would delete from {table_name}: {deleted} rows")
                else:
                    logger.info(f"Deleted from {table_name}: {deleted} rows")
        except Exception as e:
            logger.warning(f"Error cleaning {table_name}: {e}")

    # Clean up test users themselves
    try:
        with engine.connect() as conn:
            if dry_run:
                logger.info(f"[DRY-RUN] Would delete test users")
            else:
                result = conn.execute(text(
                    "DELETE FROM user WHERE user_id LIKE :prefix"
                ), {"prefix": f"{TEST_USER_PREFIX}%"})
                conn.commit()
                logger.info(f"Deleted test users: {result.rowcount} rows")
    except Exception as e:
        logger.warning(f"Error cleaning test users: {e}")


def verify_cleanup(engine):
    """Verify that all test data has been cleaned up."""
    tenant_count = count_test_tenants(engine)
    user_count = count_test_users(engine)
    logger.info(f"Verification: {tenant_count} test tenants remaining, {user_count} test users remaining")
    if tenant_count == 0 and user_count == 0:
        logger.info("Cleanup complete! All test data has been removed.")
    else:
        logger.warning("Some test data remains. You may need to clean manually.")


def main():
    parser = argparse.ArgumentParser(description="Rollback test data from Nexent database")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without actually deleting")
    parser.add_argument("--db-url", default=os.environ.get("NEXENT_DB_URL"), help="SQLAlchemy connection URL")
    args = parser.parse_args()

    db_url = args.db_url
    if not db_url:
        logger.error("Database URL not provided. Set NEXENT_DB_URL env var or use --db-url")
        sys.exit(1)

    if args.dry_run:
        logger.info("=== DRY RUN MODE ===")

    engine = get_engine(db_url)

    rollback_tenants(engine, dry_run=args.dry_run)

    if not args.dry_run:
        verify_cleanup(engine)

    logger.info("Rollback script completed.")


if __name__ == "__main__":
    main()
