"""Cross-layer contract checks for durable NL2AGENT execution context."""

import json
from pathlib import Path

from database.db_models import Nl2AgentSession


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_runner_identity_is_declared_in_every_persistence_surface() -> None:
    assert "runner_agent_id" in Nl2AgentSession.__table__.columns

    init_sql = (PROJECT_ROOT / "deploy/sql/init.sql").read_text(encoding="utf-8")
    migration_sql = (
        PROJECT_ROOT
        / "deploy/sql/migrations/v2.4.0_0722_add_nl2agent.sql"
    ).read_text(encoding="utf-8")

    assert '"runner_agent_id" int4 NOT NULL' in init_sql
    assert "runner_agent_id INTEGER NOT NULL" in migration_sql


def test_session_discovery_contract_requires_runner_identity() -> None:
    openapi = json.loads(
        (PROJECT_ROOT / "contracts/nl2agent-openapi.json").read_text(encoding="utf-8")
    )
    schema = openapi["components"]["schemas"]["Nl2AgentSessionSummaryResponse"]

    assert schema["properties"]["nl2agent_agent_id"]["type"] == "integer"
    assert "nl2agent_agent_id" in schema["required"]

    generated_types = (
        PROJECT_ROOT / "frontend/contracts/generated/nl2agent-api.ts"
    ).read_text(encoding="utf-8")
    assert "nl2agent_agent_id: number;" in generated_types
