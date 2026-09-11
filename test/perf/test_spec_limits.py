#!/usr/bin/env python3
"""
Spec limit tests for Nexent platform.

Verifies that the platform correctly enforces scale limits S-01 to S-12.

Strategy:
  1. SQLAlchemy for BULK data preparation (fast, avoids API overhead)
  2. HTTP API for verification (actual platform behavior)
  3. Verify that creating the (N+1)th resource returns an error

All test data uses perf_test_ prefix for safe rollback.
Run rollback_test_data.py after testing.

Usage:
    python test/perf/test_spec_limits.py [--skip <test_id>] [--only <test_id>]

Environment variables:
    NEXENT_BASE_URL   Nexent API base URL (default: http://localhost:8080)
    NEXENT_ADMIN_TOKEN  Admin auth token for API calls
    NEXENT_DB_URL     SQLAlchemy connection URL
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("spec_limits")

BASE_URL = os.environ.get("NEXENT_BASE_URL", "http://localhost:8080").rstrip("/")
ADMIN_TOKEN = os.environ.get("NEXENT_ADMIN_TOKEN", "")
DB_URL = os.environ.get("NEXENT_DB_URL", "")

TEST_TENANT_PREFIX = "perf_test_"
TEST_USER_PREFIX = "perf_test_user_"

SPEC_LIMITS = {
    "S-01": {"param": "max_tenants", "value": 100},
    "S-02": {"param": "max_users_per_tenant", "value": 10000},
    "S-03": {"param": "max_groups_per_tenant", "value": 1000},
    "S-04": {"param": "max_admins_per_tenant", "value": 1000},
    "S-05": {"param": "max_agents_per_tenant", "value": 1000},
    "S-06": {"param": "max_conversation_turns", "value": 100},
    "S-07": {"param": "max_conversations_per_user", "value": 1000},
    "S-08": {"param": "max_knowledge_per_tenant", "value": 10000},
    "S-09": {"param": "max_knowledge_per_user", "value": 1000},
    "S-10": {"param": "max_mcp_per_tenant", "value": 1000},
    "S-11": {"param": "max_skill_per_tenant", "value": 1000},
    "S-12": {"param": "max_memory_per_agent", "value": 10000},
}

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_engine():
    from sqlalchemy import create_engine, text
    if not DB_URL:
        raise RuntimeError("NEXENT_DB_URL not set")
    engine = create_engine(DB_URL, pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    logger.info("Database connected")
    return engine


def bulk_insert(engine, table: str, data: List[Dict]):
    from sqlalchemy import text
    if not data:
        return 0
    columns = list(data[0].keys())
    placeholders = ", ".join([f":{c}" for c in columns])
    col_names = ", ".join(columns)
    sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            for row in data:
                conn.execute(text(sql), row)
            trans.commit()
            return len(data)
        except Exception:
            trans.rollback()
            raise


def count_rows(engine, table: str, column: str, prefix: str) -> int:
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text(
            f"SELECT COUNT(*) FROM {table} WHERE {column} LIKE :prefix"
        ), {"prefix": f"{prefix}%"})
        return result.scalar()


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def api_request(method: str, path: str, data: Optional[Dict] = None) -> Tuple[int, Any]:
    import urllib.request
    import urllib.error
    import json as json_mod

    url = f"{BASE_URL}{path}"
    body = None
    headers = {
        "Authorization": f"Bearer {ADMIN_TOKEN}",
    }

    if data is not None:
        body = json_mod.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            resp_body = resp.read().decode("utf-8")
            try:
                return status, json_mod.loads(resp_body)
            except Exception:
                return status, resp_body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json_mod.loads(body)
        except Exception:
            return e.code, body
    except Exception as e:
        return 0, str(e)

# ---------------------------------------------------------------------------
# Test implementations
# ---------------------------------------------------------------------------

def prepare_test_tenant(engine, tenant_id: str) -> str:
    status, resp = api_request("POST", "/tenants", {
        "tenant_id": tenant_id,
        "tenant_name": f"Test Tenant {tenant_id}",
    })
    if status in (200, 201):
        return resp.get("tenant_id", tenant_id)
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO tenant (tenant_id, tenant_name, status, created_at) VALUES (:tid, :tn, 'active', NOW())"
        ), {"tid": tenant_id, "tn": f"Test Tenant {tenant_id}"})
        conn.commit()
    return tenant_id


def test_S01_max_tenants(engine) -> Dict:
    logger.info("=== S-01: Max tenants ===")
    limit = SPEC_LIMITS["S-01"]["value"]
    prefix = TEST_TENANT_PREFIX
    existing = count_rows(engine, "tenant", "tenant_id", prefix)
    logger.info(f"  Existing test tenants: {existing}")

    if existing < limit:
        to_create = limit - existing
        logger.info(f"  Creating {to_create} test tenants...")
        for i in range(to_create):
            tid = f"{prefix}{i}"
            try:
                prepare_test_tenant(engine, tid)
            except Exception as e:
                logger.warning(f"  Failed to create tenant {tid}: {e}")

    next_id = f"{prefix}_overflow"
    status, resp = api_request("POST", "/tenants", {
        "tenant_id": next_id,
        "tenant_name": "Overflow Test",
    })

    passed = status >= 400
    result = {
        "test_id": "S-01", "test_name": "Max tenants", "limit": limit,
        "existing": count_rows(engine, "tenant", "tenant_id", prefix),
        "overflow_status": status, "overflow_response": str(resp)[:200],
        "passed": passed,
    }
    logger.info(f"  Result: {'PASS' if passed else 'FAIL'} (status={status})")
    return result


def test_S02_max_users_per_tenant(engine) -> Dict:
    logger.info("=== S-02: Max users per tenant ===")
    limit = SPEC_LIMITS["S-02"]["value"]
    prefix = TEST_USER_PREFIX
    tenant_id = f"{TEST_TENANT_PREFIX}_users"
    prepare_test_tenant(engine, tenant_id)

    existing = count_rows(engine, "user_tenant", "user_id", prefix)
    logger.info(f"  Existing test users: {existing}")

    if existing < limit:
        to_create = min(limit - existing, 1000)
        logger.info(f"  Creating {to_create} test users (batch)...")
        batch = []
        for i in range(to_create):
            uid = f"{prefix}{i}"
            batch.append({"user_id": uid, "tenant_id": tenant_id, "user_role": "member"})
        bulk_insert(engine, "user_tenant", batch)
        user_batch = [{"user_id": f"{prefix}{i}", "user_email": f"{prefix}{i}@test.com", "user_name": f"{prefix}{i}", "status": "active"}
                      for i in range(to_create)]
        try:
            bulk_insert(engine, "user", user_batch)
        except Exception:
            pass

    next_uid = f"{prefix}_overflow"
    status, resp = api_request("POST", "/users", {
        "user_id": next_uid, "tenant_id": tenant_id,
        "user_email": f"{next_uid}@test.com", "user_name": next_uid,
    })

    passed = status >= 400
    result = {
        "test_id": "S-02", "test_name": "Max users per tenant", "limit": limit,
        "existing": count_rows(engine, "user_tenant", "user_id", prefix),
        "overflow_status": status, "overflow_response": str(resp)[:200],
        "passed": passed,
    }
    logger.info(f"  Result: {'PASS' if passed else 'FAIL'} (status={status})")
    return result


def test_S03_max_groups(engine) -> Dict:
    logger.info("=== S-03: Max groups ===")
    limit = SPEC_LIMITS["S-03"]["value"]
    prefix = "perf_test_group_"
    tenant_id = f"{TEST_TENANT_PREFIX}_groups"
    prepare_test_tenant(engine, tenant_id)

    existing = count_rows(engine, "tenant_group_info", "group_id", prefix)
    logger.info(f"  Existing test groups: {existing}")

    if existing < limit:
        to_create = min(limit - existing, 1000)
        logger.info(f"  Creating {to_create} test groups (batch)...")
        batch = []
        for i in range(to_create):
            gid = f"{prefix}{i}"
            batch.append({"group_id": gid, "tenant_id": tenant_id, "group_name": f"Test Group {i}"})
        bulk_insert(engine, "tenant_group_info", batch)

    next_gid = f"{prefix}_overflow"
    status, resp = api_request("POST", "/groups", {
        "group_id": next_gid, "tenant_id": tenant_id, "group_name": "Overflow Group",
    })

    passed = status >= 400
    result = {
        "test_id": "S-03", "test_name": "Max groups per tenant", "limit": limit,
        "existing": count_rows(engine, "tenant_group_info", "group_id", prefix),
        "overflow_status": status, "overflow_response": str(resp)[:200],
        "passed": passed,
    }
    logger.info(f"  Result: {'PASS' if passed else 'FAIL'} (status={status})")
    return result

def test_S05_max_agents(engine) -> Dict:
    logger.info("=== S-05: Max agents ===")
    limit = SPEC_LIMITS["S-05"]["value"]
    prefix = "perf_test_agent_"
    tenant_id = f"{TEST_TENANT_PREFIX}_agents"
    prepare_test_tenant(engine, tenant_id)

    existing = count_rows(engine, "agent_info", "agent_id", prefix)
    logger.info(f"  Existing test agents: {existing}")

    if existing < limit:
        to_create = min(limit - existing, 500)
        logger.info(f"  Creating {to_create} test agents (batch)...")
        batch = []
        for i in range(to_create):
            aid = f"{prefix}{i}"
            batch.append({
                "agent_id": aid, "tenant_id": tenant_id,
                "name": f"Test Agent {i}", "display_name": f"Test Agent {i}",
                "status": "active", "version": 1, "enabled": True,
            })
        bulk_insert(engine, "agent_info", batch)

    next_aid = f"{prefix}_overflow"
    status, resp = api_request("POST", "/agent/update", {
        "agent_id": next_aid,
        "agent_info": {"name": "Overflow Agent", "display_name": "Overflow Agent"},
    })

    passed = status >= 400
    result = {
        "test_id": "S-05", "test_name": "Max agents per tenant", "limit": limit,
        "existing": count_rows(engine, "agent_info", "agent_id", prefix),
        "overflow_status": status, "overflow_response": str(resp)[:200],
        "passed": passed,
    }
    logger.info(f"  Result: {'PASS' if passed else 'FAIL'} (status={status})")
    return result


def test_S06_max_conversation_turns(engine) -> Dict:
    logger.info("=== S-06: Max conversation turns ===")
    limit = SPEC_LIMITS["S-06"]["value"]
    prefix = "perf_test_msg_"
    conv_id = f"{TEST_USER_PREFIX}_conv_turns"

    status, resp = api_request("POST", "/conversation/create", {
        "conversation_id": conv_id, "title": "Turn Limit Test",
    })

    if status not in (200, 201):
        logger.warning(f"  Could not create conversation (status={status})")
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO conversation (conversation_id, title, status, created_at) VALUES (:cid, 'Turn Limit Test', 'active', NOW())"
            ), {"cid": conv_id})
            conn.commit()

    existing = count_rows(engine, "conversation_message", "message_id", prefix)
    logger.info(f"  Existing test messages: {existing}")

    if existing < limit:
        to_create = min(limit - existing, 50)
        logger.info(f"  Creating {to_create} test messages (batch)...")
        batch = []
        for i in range(to_create):
            mid = f"{prefix}{i}"
            batch.append({
                "message_id": mid, "conversation_id": conv_id,
                "role": "user", "content": f"Test message {i}",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        bulk_insert(engine, "conversation_message", batch)

    status, resp = api_request("POST", "/conversation/save", {
        "conversation_id": conv_id,
        "message": {"role": "user", "content": "Overflow message"},
    })

    passed = status >= 400
    result = {
        "test_id": "S-06", "test_name": "Max conversation turns", "limit": limit,
        "existing": count_rows(engine, "conversation_message", "message_id", prefix),
        "overflow_status": status, "overflow_response": str(resp)[:200],
        "passed": passed,
    }
    logger.info(f"  Result: {'PASS' if passed else 'FAIL'} (status={status})")
    return result


def test_S07_max_conversations(engine) -> Dict:
    logger.info("=== S-07: Max conversations per user ===")
    limit = SPEC_LIMITS["S-07"]["value"]
    prefix = "perf_test_conv_"
    user_id = f"{TEST_USER_PREFIX}_conv"

    existing = count_rows(engine, "conversation", "conversation_id", prefix)
    logger.info(f"  Existing test conversations: {existing}")

    if existing < limit:
        to_create = min(limit - existing, 500)
        logger.info(f"  Creating {to_create} test conversations (batch)...")
        batch = []
        for i in range(to_create):
            cid = f"{prefix}{i}"
            batch.append({
                "conversation_id": cid, "user_id": user_id,
                "title": f"Test Conv {i}", "status": "active",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        bulk_insert(engine, "conversation", batch)

    next_cid = f"{prefix}_overflow"
    status, resp = api_request("POST", "/conversation/create", {
        "conversation_id": next_cid, "user_id": user_id, "title": "Overflow Conversation",
    })

    passed = status >= 400
    result = {
        "test_id": "S-07", "test_name": "Max conversations per user", "limit": limit,
        "existing": count_rows(engine, "conversation", "conversation_id", prefix),
        "overflow_status": status, "overflow_response": str(resp)[:200],
        "passed": passed,
    }
    logger.info(f"  Result: {'PASS' if passed else 'FAIL'} (status={status})")
    return result

def test_S08_max_knowledge(engine) -> Dict:
    logger.info("=== S-08: Max knowledge per tenant ===")
    limit = SPEC_LIMITS["S-08"]["value"]
    prefix = "perf_test_kb_"
    tenant_id = f"{TEST_TENANT_PREFIX}_kb"
    prepare_test_tenant(engine, tenant_id)

    existing = count_rows(engine, "knowledge_record", "knowledge_id", prefix)
    logger.info(f"  Existing test knowledge bases: {existing}")

    if existing < limit:
        to_create = min(limit - existing, 2000)
        logger.info(f"  Creating {to_create} test knowledge bases (batch)...")
        batch = []
        for i in range(to_create):
            kid = f"{prefix}{i}"
            batch.append({
                "knowledge_id": kid, "tenant_id": tenant_id,
                "knowledge_name": f"Test KB {i}", "index_name": f"test_index_{i}",
                "status": "active",
            })
        bulk_insert(engine, "knowledge_record", batch)

    next_kid = f"{prefix}_overflow"
    status, resp = api_request("POST", "/indices", {
        "knowledge_id": next_kid, "tenant_id": tenant_id,
        "knowledge_name": "Overflow KB",
    })

    passed = status >= 400
    result = {
        "test_id": "S-08", "test_name": "Max knowledge per tenant", "limit": limit,
        "existing": count_rows(engine, "knowledge_record", "knowledge_id", prefix),
        "overflow_status": status, "overflow_response": str(resp)[:200],
        "passed": passed,
    }
    logger.info(f"  Result: {'PASS' if passed else 'FAIL'} (status={status})")
    return result


def test_S10_max_mcp(engine) -> Dict:
    logger.info("=== S-10: Max MCP services ===")
    limit = SPEC_LIMITS["S-10"]["value"]
    prefix = "perf_test_mcp_"
    tenant_id = f"{TEST_TENANT_PREFIX}_mcp"
    prepare_test_tenant(engine, tenant_id)

    existing = count_rows(engine, "mcp_server", "mcp_id", prefix)
    logger.info(f"  Existing test MCP services: {existing}")

    if existing < limit:
        to_create = min(limit - existing, 500)
        logger.info(f"  Creating {to_create} test MCP services (batch)...")
        batch = []
        for i in range(to_create):
            mid = f"{prefix}{i}"
            batch.append({
                "mcp_id": mid, "tenant_id": tenant_id,
                "mcp_name": f"Test MCP {i}", "mcp_url": f"http://test-{i}.com/mcp",
                "status": "active",
            })
        bulk_insert(engine, "mcp_server", batch)

    next_mid = f"{prefix}_overflow"
    status, resp = api_request("POST", "/mcp-tools", {
        "mcp_id": next_mid, "tenant_id": tenant_id,
        "mcp_name": "Overflow MCP", "mcp_url": "http://test-overflow.com/mcp",
    })

    passed = status >= 400
    result = {
        "test_id": "S-10", "test_name": "Max MCP per tenant", "limit": limit,
        "existing": count_rows(engine, "mcp_server", "mcp_id", prefix),
        "overflow_status": status, "overflow_response": str(resp)[:200],
        "passed": passed,
    }
    logger.info(f"  Result: {'PASS' if passed else 'FAIL'} (status={status})")
    return result


def test_S11_max_skills(engine) -> Dict:
    logger.info("=== S-11: Max skills ===")
    limit = SPEC_LIMITS["S-11"]["value"]
    prefix = "perf_test_skill_"
    tenant_id = f"{TEST_TENANT_PREFIX}_skills"
    prepare_test_tenant(engine, tenant_id)

    existing = count_rows(engine, "skill_info", "skill_id", prefix)
    logger.info(f"  Existing test skills: {existing}")

    if existing < limit:
        to_create = min(limit - existing, 500)
        logger.info(f"  Creating {to_create} test skills (batch)...")
        batch = []
        for i in range(to_create):
            sid = f"{prefix}{i}"
            batch.append({
                "skill_id": sid, "tenant_id": tenant_id,
                "skill_name": f"TestSkill{i}", "status": "active",
            })
        bulk_insert(engine, "skill_info", batch)

    next_sid = f"{prefix}_overflow"
    status, resp = api_request("POST", "/skills", {
        "skill_id": next_sid, "tenant_id": tenant_id,
        "skill_name": "OverflowSkill",
    })

    passed = status >= 400
    result = {
        "test_id": "S-11", "test_name": "Max skills per tenant", "limit": limit,
        "existing": count_rows(engine, "skill_info", "skill_id", prefix),
        "overflow_status": status, "overflow_response": str(resp)[:200],
        "passed": passed,
    }
    logger.info(f"  Result: {'PASS' if passed else 'FAIL'} (status={status})")
    return result


def test_S12_max_memory(engine) -> Dict:
    logger.info("=== S-12: Max memory entries ===")
    limit = SPEC_LIMITS["S-12"]["value"]
    prefix = "perf_test_mem_"
    tenant_id = f"{TEST_TENANT_PREFIX}_memory"
    agent_id = f"{TEST_USER_PREFIX}_memory_agent"
    prepare_test_tenant(engine, tenant_id)

    from sqlalchemy import text
    with engine.connect() as conn:
        try:
            conn.execute(text(
                "INSERT INTO agent_info (agent_id, tenant_id, name, display_name, status, version, enabled) VALUES (:aid, :tid, 'Memory Agent', 'Memory Agent', 'active', 1, True)"
            ), {"aid": agent_id, "tid": tenant_id})
            conn.commit()
        except Exception:
            pass

    existing = count_rows(engine, "memory_record", "memory_id", prefix)
    logger.info(f"  Existing test memory entries: {existing}")

    if existing < limit:
        to_create = min(limit - existing, 2000)
        logger.info(f"  Creating {to_create} test memory entries (batch)...")
        batch = []
        for i in range(to_create):
            mid = f"{prefix}{i}"
            batch.append({
                "memory_id": mid, "tenant_id": tenant_id,
                "agent_id": agent_id, "user_id": f"{TEST_USER_PREFIX}_mem_user",
                "content": f"Test memory {i}", "layer": "episodic",
                "status": "active",
            })
        bulk_insert(engine, "memory_record", batch)

    next_mid = f"{prefix}_overflow"
    status, resp = api_request("POST", "/memory/records", {
        "memory_id": next_mid, "tenant_id": tenant_id,
        "agent_id": agent_id, "content": "Overflow memory entry",
        "layer": "episodic",
    })

    passed = status >= 400
    result = {
        "test_id": "S-12", "test_name": "Max memory entries per agent", "limit": limit,
        "existing": count_rows(engine, "memory_record", "memory_id", prefix),
        "overflow_status": status, "overflow_response": str(resp)[:200],
        "passed": passed,
    }
    logger.info(f"  Result: {'PASS' if passed else 'FAIL'} (status={status})")
    return result

# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

TEST_FUNCTIONS = {
    "S-01": test_S01_max_tenants,
    "S-02": test_S02_max_users_per_tenant,
    "S-03": test_S03_max_groups,
    "S-05": test_S05_max_agents,
    "S-06": test_S06_max_conversation_turns,
    "S-07": test_S07_max_conversations,
    "S-08": test_S08_max_knowledge,
    "S-10": test_S10_max_mcp,
    "S-11": test_S11_max_skills,
    "S-12": test_S12_max_memory,
}


def main():
    parser = argparse.ArgumentParser(description="Nexent spec limit tests")
    parser.add_argument("--skip", nargs="*", help="Test IDs to skip")
    parser.add_argument("--only", nargs="*", help="Only run specific test IDs")
    parser.add_argument("--db-url", default=DB_URL, help="SQLAlchemy connection URL")
    parser.add_argument("--base-url", default=BASE_URL, help="Nexent API base URL")
    parser.add_argument("--token", default=ADMIN_TOKEN, help="Admin auth token")
    args = parser.parse_args()

    global BASE_URL, ADMIN_TOKEN, DB_URL
    BASE_URL = args.base_url
    ADMIN_TOKEN = args.token
    DB_URL = args.db_url

    if not DB_URL:
        logger.error("Database URL not provided. Set NEXENT_DB_URL or use --db-url")
        sys.exit(1)

    engine = get_engine()

    skip_set = set(args.skip or [])
    only_set = set(args.only or [])
    tests_to_run = {}
    for tid, func in TEST_FUNCTIONS.items():
        if only_set and tid not in only_set:
            continue
        if tid in skip_set:
            continue
        tests_to_run[tid] = func

    logger.info(f"Will run {len(tests_to_run)} spec tests: {sorted(tests_to_run.keys())}")
    logger.info(f"Reference values: { {k: v['value'] for k, v in SPEC_LIMITS.items()} }")

    results = []
    start_time = time.time()

    for tid, func in sorted(tests_to_run.items()):
        try:
            result = func(engine)
            results.append(result)
        except Exception as e:
            logger.error(f"Test {tid} failed with exception: {e}")
            results.append({
                "test_id": tid, "test_name": SPEC_LIMITS[tid]["param"],
                "limit": SPEC_LIMITS[tid]["value"],
                "passed": False, "error": str(e)[:200],
            })

    elapsed = time.time() - start_time
    passed = sum(1 for r in results if r.get("passed"))
    failed = sum(1 for r in results if not r.get("passed"))

    logger.info(f"\n{'='*60}")
    logger.info(f"SPEC TEST SUMMARY: {passed} passed, {failed} failed, {len(results)} total")
    logger.info(f"Elapsed: {elapsed:.1f}s")
    logger.info(f"{'='*60}")

    for r in results:
        status = "PASS" if r.get("passed") else "FAIL"
        logger.info(f"  [{status}] {r['test_id']} - {r['test_name']} (limit={r['limit']})")
        if not r.get("passed"):
            logger.info(f"         Detail: {json.dumps({k: v for k, v in r.items() if k not in ['test_id', 'test_name', 'limit', 'passed']}, ensure_ascii=False)[:200]}")

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": elapsed,
        "summary": {"passed": passed, "failed": failed, "total": len(results)},
        "results": results,
    }
    output_path = "spec_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    logger.info(f"Results saved to {output_path}")
    logger.info("\nREMEMBER: Run rollback_test_data.py to clean up test data!")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
