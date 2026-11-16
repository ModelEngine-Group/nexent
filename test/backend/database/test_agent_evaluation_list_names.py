# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import nullcontext

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


def test_list_agent_names_are_tenant_scoped_and_preserve_the_run_window(mocker):
    from management.db.evaluation import runs as db

    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        run_table = db.AgentEvaluation.__table__
        if run_table.schema:
            connection.exec_driver_sql(f'ATTACH DATABASE ":memory:" AS "{run_table.schema}"')

        # The read query needs column names but no PostgreSQL defaults or constraints.
        columns = {
            db.AgentEvaluation: list(run_table.columns.keys()),
            db.AgentInfo: ["agent_id", "tenant_id", "version_no", "display_name", "name"],
            db.EvaluationSet: ["evaluation_set_id", "tenant_id", "name"],
            db.ModelRecord: ["model_id", "tenant_id", "display_name"],
        }
        for model, names in columns.items():
            connection.exec_driver_sql(
                f"CREATE TABLE {model.__table__.fullname} ({', '.join(names)})"
            )

        connection.exec_driver_sql(
            f"INSERT INTO {db.AgentInfo.__table__.fullname} VALUES (?, ?, ?, ?, ?)",
            [
                (7, "local", 1, "Older name", "older_name"),
                (7, "local", 2, "Historical agent", "historical_agent"),
                (7, "other", 3, "Other tenant name", "other_tenant_name"),
                (8, "local", 1, "", "programmatic_name"),
                (9, "other", 1, "Foreign agent", "foreign_agent"),
            ],
        )
        connection.exec_driver_sql(
            f"INSERT INTO {run_table.fullname} "
            "(agent_evaluation_id, agent_id, tenant_id, agent_version_no, create_time) "
            "VALUES (?, ?, ?, 1, ?)",
            [
                (101, 7, "local", "2026-11-03 12:00:00"),
                (102, 8, "local", "2026-11-03 11:00:00"),
                (103, 9, "local", "2026-11-03 10:00:00"),
                (104, 7, "other", "2026-11-03 13:00:00"),
            ],
        )

    with Session(engine) as session:
        mocker.patch.object(db, "get_db_session", return_value=nullcontext(session))
        rows = db.list_agent_evaluations_by_agent([], "local", limit=0)
        assert [(row["agent_evaluation_id"], row["agent_name"]) for row in rows] == [
            (101, "Historical agent"),
            (102, "programmatic_name"),
            (103, ""),
        ]
        page = db.list_agent_evaluations_by_agent([7, 9], "local", limit=1, offset=1)
        assert [(row["agent_evaluation_id"], row["agent_name"]) for row in page] == [(103, "")]
