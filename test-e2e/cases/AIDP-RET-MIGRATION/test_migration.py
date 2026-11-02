# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute the actual migration SQL in run-owned PostgreSQL containers."""

import json
import subprocess
import time
import uuid
from pathlib import Path

import pytest

pytestmark = [pytest.mark.case_id("AIDP-RET-MIGRATION"), pytest.mark.stage("D5")]

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "deploy/sql/migrations/v2.8.0_aidp_fixed_retrieval_policy.sql"
NEW_KEYS = {
    "vector_candidates", "full_text_candidates", "hybrid_top_k", "graph_top_k",
    "vector_score_threshold", "full_text_score_threshold", "graph_score_threshold",
    "graph_reranking_enable", "query_expansion_enable",
}
SEED = """
CREATE SCHEMA nexent;
CREATE TABLE nexent.ag_tool_info_t (
    tool_id integer PRIMARY KEY, name text, class_name text, params json
);
CREATE TABLE nexent.ag_tool_instance_t (
    tool_instance_id integer, version_no integer, tool_id integer,
    tenant_id text, enabled boolean, delete_flag text, params json,
    PRIMARY KEY (tool_instance_id, version_no)
);
INSERT INTO nexent.ag_tool_info_t VALUES
 (11, 'aidp_search', 'AidpSearchTool',
  '[{"name":"top_k","default":10},{"name":"custom","default":"keep"},
    {"name":"vector_candidates","default":999}]'),
 (22, 'ind_aidp_search', 'IndependentAidpSearchTool', '[]'),
 (33, 'other_tool', 'OtherTool', '[{"name":"custom","default":"untouched"}]'),
 (44, 'aidp_search', NULL, '[]');
INSERT INTO nexent.ag_tool_instance_t VALUES
 (101,0,11,'tenant-a',true,'N',
  '{"top_k":7,"reranking_enable":false,"search_method":"hybrid_search","kds_list":["kb-a"]}'),
 (101,1,11,'tenant-a',false,'Y',
  '{"top_k":7.0,"reranking_enable":false,"search_method":"hybrid_search","kds_list":["kb-old"]}'),
 (101,2,11,'tenant-a',true,'N',
  '{"top_k":"7","reranking_enable":false,"search_method":"full_text_search","kds_list":["kb-published"]}'),
 (102,0,22,'tenant-b',false,'Y','{"kds_list":["kb-b"],"server_url":"https://example.invalid","api_key":"fixture-only"}'),
 (103,0,22,'tenant-b',true,'N',
  '{"top_k":9,"vector_candidates":30,"full_text_candidates":40,
    "hybrid_top_k":4,"graph_top_k":2,"vector_score_threshold":0.1,
    "full_text_score_threshold":0.2,"graph_score_threshold":0.3,
    "graph_reranking_enable":false,"query_expansion_enable":true,
    "reranking_enable":true,"search_method":"vector_search|graph_search",
    "multi_modal":false,"kds_list":["kb-fixed"],"custom":{"keep":true}}'),
 (104,0,22,'tenant-c',true,'N',
  '{"top_k":8,"vector_candidates":18,"full_text_candidates":28,
    "hybrid_top_k":0,"graph_top_k":0,"graph_reranking_enable":false,
    "query_expansion_enable":false,"reranking_enable":false,"score_threshold":0}'),
 (105,0,33,'tenant-c',true,'N','{"top_k":"7","custom":"untouched"}'),
 (106,0,44,'tenant-d',true,'N','{"top_k":"8","kds_list":["kb-legacy-name"]}');
"""


def docker(*args, input_text=None, check=True):
    result = subprocess.run(
        ["docker", *map(str, args)], input=input_text, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=90,
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


class Postgres:
    def __init__(self, name):
        self.name = name

    def sql(self, statement):
        return docker(
            "exec", "-i", self.name, "psql", "-U", "postgres", "-d", "postgres",
            "-At", "-v", "ON_ERROR_STOP=1", input_text=statement,
        ).stdout.strip()

    def migrate(self):
        return self.sql(MIGRATION.read_text(encoding="utf-8"))

    def instances(self):
        return json.loads(self.sql("""
            SELECT json_agg(i ORDER BY tool_instance_id, version_no)
            FROM nexent.ag_tool_instance_t i;
        """))

    def snapshot(self):
        return self.sql("""
            SELECT jsonb_agg(to_jsonb(s) ORDER BY kind, id, version_no) FROM (
                SELECT 'catalog' kind, tool_id id, 0 version_no, params::jsonb,
                       xmin::text row_version FROM nexent.ag_tool_info_t
                UNION ALL
                SELECT 'instance', tool_instance_id, version_no, params::jsonb,
                       xmin::text FROM nexent.ag_tool_instance_t
            ) s;
        """)


@pytest.fixture
def postgres():
    docker("image", "inspect", "postgres:15-alpine")
    name = "nexent-aidp-migration-" + uuid.uuid4().hex[:12]
    container_id = None
    try:
        container_id = docker(
            "run", "--rm", "-d", "--name", name, "--network", "none",
            "--tmpfs", "/var/lib/postgresql/data:rw", "--label", "nexent.case=AIDP-RET-MIGRATION",
            "-e", "POSTGRES_PASSWORD=fixture-only", "postgres:15-alpine",
        ).stdout.strip()
        for _ in range(120):
            if docker("exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", check=False).returncode == 0:
                break
            time.sleep(0.25)
        else:
            pytest.fail("The disposable PostgreSQL container did not become ready")
        pg = Postgres(name)
        pg.sql(SEED)
        yield pg
    finally:
        if container_id:
            docker("stop", "-t", "1", container_id)


def test_legacy_numeric_representations(postgres):
    postgres.migrate()
    rows = postgres.instances()
    for row in rows:
        if row["tool_instance_id"] == 101:
            params = row["params"]
            for key in ["top_k", "vector_candidates", "full_text_candidates"]:
                assert type(params[key]) is int and params[key] == 7, (row, key)
            assert params["graph_reranking_enable"] is False
            assert params["hybrid_top_k"] == params["graph_top_k"] == 0
            assert params["query_expansion_enable"] is False
    sparse = next(row["params"] for row in rows if row["tool_instance_id"] == 102)
    assert "top_k" not in sparse
    assert sparse["vector_candidates"] == sparse["full_text_candidates"] == 10
    assert sparse["graph_reranking_enable"] is True
    by_name = next(row["params"] for row in rows if row["tool_instance_id"] == 106)
    assert by_name["top_k"] == by_name["vector_candidates"] == by_name["full_text_candidates"] == 8


def test_preserves_versions_policies_and_unrelated_values(postgres):
    before = postgres.instances()
    postgres.migrate()
    after = postgres.instances()
    for original, migrated in zip(before, after, strict=True):
        assert {k: v for k, v in original.items() if k != "params"} == {
            k: v for k, v in migrated.items() if k != "params"
        }
        if original["tool_id"] == 33:
            assert migrated == original
            continue
        for key, value in original["params"].items():
            if key not in {"top_k", "search_method"}:
                assert migrated["params"][key] == value, (original, migrated, key)
        assert NEW_KEYS <= migrated["params"].keys()
        expected_method = original["params"].get("search_method", "hybrid_search")
        if expected_method == "hybrid_search":
            expected_method = "vector_search|full_text_search|graph_search"
        assert migrated["params"]["search_method"] == expected_method


def test_directory_and_reapply_avoid_row_rewrites(postgres):
    postgres.migrate()
    catalogs = json.loads(postgres.sql("SELECT json_agg(t ORDER BY tool_id) FROM nexent.ag_tool_info_t t;"))
    for tool in catalogs:
        if tool["tool_id"] == 33:
            assert tool["params"] == [{"name": "custom", "default": "untouched"}]
            continue
        names = [param["name"] for param in tool["params"]]
        assert all(names.count(key) == 1 for key in NEW_KEYS)
        if tool["tool_id"] == 11:
            assert names[:2] == ["top_k", "custom"]
            assert tool["params"][1] == {"name": "custom", "default": "keep"}
        vector = next(param for param in tool["params"] if param["name"] == "vector_candidates")
        assert vector["default"] == 10 and vector["constraints"] == {"ge": 1, "le": 500}
    before = postgres.snapshot()
    assert postgres.migrate().splitlines() == ["UPDATE 0", "UPDATE 0"]
    assert postgres.snapshot() == before
