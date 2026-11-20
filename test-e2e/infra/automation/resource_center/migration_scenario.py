# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise the shipped migration runner on a disposable PostgreSQL database."""

import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import uuid


def run_migration_scenario():
    repo = Path(__file__).resolve().parents[4]
    home = Path(os.environ["NEXENT_TEST_HOME"])
    config = json.loads((home / "config/resource-center.json").read_text(encoding="utf-8"))
    container = config["database_container"]
    runner_container = config["backend_container"]
    name = "rsc_upgrade_" + uuid.uuid4().hex
    remote = "/tmp/" + name

    def execute(arguments, *, content=None, success=True):
        result = subprocess.run(arguments, input=content, text=True, capture_output=True,
                                encoding="utf-8", timeout=180)
        if success:
            assert result.returncode == 0, (result.stdout + result.stderr)[-6000:]
        return result

    def sql(statement):
        return execute(["docker", "exec", "-i", container, "psql", "-U", "root", "-d", name,
                        "-v", "ON_ERROR_STOP=1", "-At"], content=statement).stdout.strip()

    tracked = execute(["git", "ls-files", "deploy/sql"]).stdout.splitlines()
    created = False
    try:
        execute(["docker", "exec", container, "createdb", "-U", "root", name])
        created = True
        with tempfile.TemporaryDirectory(prefix="rsc-migration-") as directory:
            archive = Path(directory) / "migration.tar"
            with tarfile.open(archive, "w") as tar:
                for path in tracked:
                    if path.endswith(".sql"):
                        tar.add(repo / path, arcname="baseline/" + Path(path).relative_to("deploy/sql").as_posix())
                for path in (repo / "deploy/sql").rglob("*.sql"):
                    tar.add(path, arcname="target/" + path.relative_to(repo / "deploy/sql").as_posix())
                tar.add(repo / "deploy/common/run-sql-migrations.sh", arcname="runner.sh")
            execute(["docker", "cp", str(archive), f"{runner_container}:{remote}.tar"])
        execute(["docker", "exec", runner_container, "mkdir", "-p", remote])
        execute(["docker", "exec", runner_container, "tar", "-xf", remote + ".tar", "-C", remote])

        def migrate(folder, *, success=True):
            return execute(["docker", "exec", "-e", f"POSTGRES_HOST={container}", "-e", "POSTGRES_USER=root",
                            "-e", f"POSTGRES_DB={name}", "-e", f"NEXENT_SQL_INIT_FILE={remote}/{folder}/init.sql",
                            "-e", f"NEXENT_SQL_MIGRATION_DIR={remote}/{folder}/migrations", "-e", "NEXENT_APP_VERSION=2.8.0",
                            runner_container, "bash", remote + "/runner.sh", "--migrate"], success=success)

        migrate("baseline")
        actor, reviewer, outsider = [str(uuid.uuid4()) for _ in range(3)]
        sql(f"""
INSERT INTO nexent.user_tenant_t(user_id,tenant_id,user_role,user_email,delete_flag)
VALUES ('{actor}','rsc-upgrade','DEV','owner@example.invalid','N'),
       ('{reviewer}','rsc-upgrade','ADMIN','reviewer@example.invalid','N'),
       ('{outsider}','rsc-upgrade','DEV','other@example.invalid','N');
INSERT INTO nexent.ag_tenant_agent_t(agent_id,version_no,tenant_id,name,created_by,delete_flag)
VALUES (1,1,'rsc-upgrade','legacy-agent','{actor}','N');
INSERT INTO nexent.ag_skill_info_t(skill_id,skill_name,tenant_id,source,created_by,delete_flag)
VALUES (1,'legacy-skill','rsc-upgrade','repository','{actor}','N');
INSERT INTO nexent.mcp_record_t(mcp_id,tenant_id,user_id,mcp_name,created_by,delete_flag)
VALUES (1,'rsc-upgrade','{actor}','legacy-mcp','{actor}','N');
INSERT INTO nexent.ag_agent_repository_t(agent_id,version_no,name,agent_info_json,publisher_tenant_id,publisher_user_id,content,status,update_time,delete_flag)
VALUES (1,1,'legacy-agent','{{"agent_id":1,"agent_info":{{}},"mcp_info":[]}}','rsc-upgrade','publisher','legacy note','pending_review','2026-01-02 03:04:05','N'),
       (2,1,'historical-shared','{{"agent_id":2,"agent_info":{{}},"mcp_info":[]}}','rsc-upgrade','publisher','old publication','shared','2026-01-01','N');
INSERT INTO nexent.ag_skill_repository_t(skill_id,name,skill_info_json,skill_zip_base64,publisher_tenant_id,publisher_user_id,content,status,update_time,delete_flag)
VALUES (1,'legacy-skill','{{}}','UEsFBgAAAAAAAAAAAAAAAAAAAAAAAA==','rsc-upgrade','publisher','legacy note','pending_review','2026-01-02 03:04:05','N');
INSERT INTO nexent.mcp_market_record_t(mcp_name,mcp_server,transport_type,tenant_id,user_id,source_mcp_id,content,review_status,update_time,delete_flag)
VALUES ('legacy-mcp','https://example.invalid','url','rsc-upgrade','publisher',1,'legacy note','pending_review','2026-01-02 03:04:05','N');
""")
        def expect_failed_upgrade():
            failed = migrate("target", success=False)
            assert failed.returncode != 0
            assert sql("SELECT to_regclass('nexent.ag_resource_review_t') IS NULL") == "t"

        sql("UPDATE nexent.ag_tenant_agent_t SET created_by=NULL WHERE agent_id=1")
        expect_failed_upgrade()
        sql(f"UPDATE nexent.ag_tenant_agent_t SET created_by='{actor}' WHERE agent_id=1")
        sql("ALTER TABLE nexent.ag_agent_repository_t DISABLE TRIGGER USER; UPDATE nexent.ag_agent_repository_t SET agent_info_json='{}' WHERE agent_id=1; ALTER TABLE nexent.ag_agent_repository_t ENABLE TRIGGER USER")
        expect_failed_upgrade()
        sql("ALTER TABLE nexent.ag_agent_repository_t DISABLE TRIGGER USER; UPDATE nexent.ag_agent_repository_t SET agent_info_json='{\"agent_id\":1,\"agent_info\":{},\"mcp_info\":[]}',update_time=NULL WHERE agent_id=1; ALTER TABLE nexent.ag_agent_repository_t ENABLE TRIGGER USER")
        expect_failed_upgrade()
        sql("ALTER TABLE nexent.ag_agent_repository_t DISABLE TRIGGER USER; UPDATE nexent.ag_agent_repository_t SET update_time='2026-01-02 03:04:05' WHERE agent_id=1; ALTER TABLE nexent.ag_agent_repository_t ENABLE TRIGGER USER")
        sql("INSERT INTO nexent.mcp_market_record_t(mcp_name,mcp_server,transport_type,tenant_id,user_id,source_mcp_id,content,review_status,delete_flag) VALUES ('duplicate-pending','https://example.invalid','url','rsc-upgrade','publisher',1,'duplicate','pending_review','N')")
        expect_failed_upgrade()
        sql("DELETE FROM nexent.mcp_market_record_t WHERE mcp_name='duplicate-pending'")
        migrate("target")
        assert sql("SELECT count(*) FROM nexent.ag_resource_review_t") == "3"
        assert sql(f"SELECT count(*) FROM nexent.ag_resource_review_t WHERE submitted_user_id='{actor}' AND submit_description='legacy note' AND submitted_at='2026-01-02 03:04:05+00' AND review_status='pending_review'") == "3"
        assert sql("SELECT count(*) FROM information_schema.columns WHERE table_schema='nexent' AND table_name IN ('ag_agent_repository_t','ag_skill_repository_t','mcp_market_record_t') AND column_name IN ('submitted_user_id','submitted_at','submit_description','review_comment','submission_revision','published_at')") == "0"
        assert sql("SELECT count(*) FROM information_schema.columns WHERE table_schema='nexent' AND table_name='ag_skill_info_t' AND column_name='source_repository_id'") == "1"
        assert sql("SELECT count(*) FROM nexent.ag_skill_info_t WHERE skill_name='legacy-skill' AND source_repository_id IS NULL") == "1"
        assert sql("SELECT count(*) FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='nexent' AND c.relname='ag_resource_review_t' AND a.attnum>0 AND NOT a.attisdropped AND col_description(c.oid,a.attnum) IS NOT NULL") == "19"
        assert sql("SELECT count(*) FROM pg_indexes WHERE schemaname='nexent' AND indexname LIKE 'idx_resource_review_%'") == "4"
        grants = json.loads(sql("SELECT json_agg(user_role ORDER BY user_role) FROM nexent.role_permission_t WHERE permission_subtype='/resource-space' AND permission_type='LEFT_NAV_MENU'"))
        assert grants == ["ADMIN", "ASSET_OWNER", "DEV", "SPEED"]
        ledger_before = sql("SELECT count(*) FROM nexent.schema_migrations")
        ids_before = sql("SELECT string_agg(review_id::text,',' ORDER BY review_id) FROM nexent.ag_resource_review_t")
        migrate("target")
        assert sql("SELECT count(*) FROM nexent.schema_migrations") == ledger_before
        assert sql("SELECT string_agg(review_id::text,',' ORDER BY review_id) FROM nexent.ag_resource_review_t") == ids_before
        smoke = f"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway.authentication.auth import generate_session_jwt
from management.api.repository.reviews import router
from management.api.agent.agent_repository import agent_repository_router
app = FastAPI()
app.include_router(agent_repository_router)
app.include_router(router)
with TestClient(app) as client:
    mine = {{'Authorization': 'Bearer ' + generate_session_jwt('{actor}')}}
    admin = {{'Authorization': 'Bearer ' + generate_session_jwt('{reviewer}')}}
    other = {{'Authorization': 'Bearer ' + generate_session_jwt('{outsider}')}}
    assert client.get('/reviews',headers=mine).json()['pagination']['total']==3
    assert client.get('/reviews',headers=other).json()['pagination']['total']==0
    detail=client.get('/reviews/agent/1',headers=admin)
    assert detail.status_code==200,detail.text
    identity=detail.json()['review_id']
    approved=client.patch('/repository/agent/1/status',headers=admin,json={{'status':'shared','content':'approved'}})
    assert approved.status_code==200,approved.text
    result=client.get('/reviews/'+identity,headers=mine).json()
    assert result['status']=='approved' and result['repository_id']=='1'
    assert result['submitted_user_id']=='{actor}' and result['reviewed_at']
    assert result['submit_description']=='legacy note' and result['review_comment']=='approved'
print('Real upgraded database: legacy decision writes new review result; internal submitter scope retained.')
"""
        execute(["docker", "exec", "-i", "-w", config["backend_directory"], "-e", f"POSTGRES_DB={name}",
                 runner_container, config["python"], "-"], content=smoke)
        # Exercise the runner failure ledger without changing product migration files.
        execute(["docker", "exec", "-i", runner_container, "sh", "-c", f"cat > {remote}/target/migrations/v999_999_controlled_failure.sql"],
                content="BEGIN; CREATE TABLE nexent.expected_rollback_fixture(id INTEGER); SELECT 1/0; COMMIT;\n")
        assert migrate("target", success=False).returncode != 0
        assert sql("SELECT count(*) FROM nexent.schema_migrations WHERE migration_id LIKE '%controlled_failure%'") == "0"
        assert sql("SELECT count(*) FROM information_schema.tables WHERE table_schema='nexent' AND table_name='expected_rollback_fixture'") == "0"
        print("Formal upgrade runner: pending-only migration, comments, scopes, retained Skill source, idempotency and rollback ledger passed.")
    finally:
        if created:
            execute(["docker", "exec", container, "dropdb", "-U", "root", "--force", name])
        execute(["docker", "exec", runner_container, "rm", "-rf", remote, remote + ".tar"])
