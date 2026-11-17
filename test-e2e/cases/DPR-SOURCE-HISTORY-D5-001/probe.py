# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute the packaged migration and production source writes in owned PostgreSQL."""

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

assert not Path("/opt/backend/runtime").exists()
with (
    patch(
        "nexent.storage.storage_client_factory.create_storage_client_from_config",
        return_value=MagicMock(),
    ),
    patch("nexent.storage.minio_config.MinIOStorageConfig.validate", lambda self: None),
):
    from management.db.conversation import repository
    from management.db.models import (
        ConversationMessage,
        ConversationMessageUnit,
        ConversationRecord,
        ConversationSourceSearch,
    )
from management.services.agent.stream import AssistantMessageProjection

engine = create_engine(
    "postgresql+psycopg2://fixture-user:fixture-password@127.0.0.1:5432/source_reference"
)


@contextmanager
def session_scope():
    with Session(engine) as session, session.begin():
        session.execute(text("SET LOCAL statement_timeout = '10s'"))
        yield session


repository.get_db_session = session_scope
migration = Path("/opt/deploy/sql/migrations/v2.9.0_018_knowledge_source_reference.sql")
try:
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA nexent")
        for model in (
            ConversationRecord,
            ConversationMessage,
            ConversationMessageUnit,
            ConversationSourceSearch,
        ):
            model.__table__.create(connection)
        connection.exec_driver_sql(
            "ALTER TABLE nexent.conversation_source_search_t DROP COLUMN knowledge_reference"
        )
        connection.exec_driver_sql(
            "INSERT INTO nexent.conversation_source_search_t (search_id, source_title) VALUES (900, 'legacy')"
        )
        for _ in range(2):
            connection.exec_driver_sql(migration.read_text())
        column = connection.execute(
            text("""
            SELECT data_type, is_nullable FROM information_schema.columns
            WHERE table_schema='nexent' AND table_name='conversation_source_search_t' AND column_name='knowledge_reference'
        """)
        ).one()
        assert tuple(column) == ("jsonb", "YES")
        comment = connection.scalar(
            text("""
            SELECT col_description('nexent.conversation_source_search_t'::regclass, attnum)
            FROM pg_attribute WHERE attrelid='nexent.conversation_source_search_t'::regclass AND attname='knowledge_reference'
        """)
        )
        assert (
            comment == ConversationSourceSearch.__table__.c.knowledge_reference.comment
        )
        assert connection.execute(
            text(
                "SELECT source_title, knowledge_reference FROM nexent.conversation_source_search_t WHERE search_id=900"
            )
        ).one() == ("legacy", None)
    with session_scope() as session:
        session.add(
            ConversationRecord(
                conversation_id=1,
                conversation_title="owned",
                created_by="owner",
                delete_flag="N",
            )
        )
        for identity in (1, 2):
            session.add(
                ConversationMessage(
                    message_id=identity,
                    conversation_id=1,
                    message_index=identity,
                    message_role="assistant",
                    message_content="",
                    status="streaming",
                    created_by="owner",
                    delete_flag="N",
                )
            )
    reference = {
        "file_ref": {"knowledge_id": 1, "file_id": "a" * 32, "file_version": 2},
        "image_ref": {
            "space": "files",
            "key": "images/reference.png",
            "version": "etag:fixed",
            "sha256": "b" * 64,
        },
        "location": {"page_number": 3},
    }
    projection = AssistantMessageProjection(persist_units=True)
    projection.project(
        json.dumps(
            {
                "type": "search_content",
                "content": json.dumps(
                    [
                        {
                            "title": "report",
                            "url": "",
                            "text": "fact",
                            "cite_index": 1,
                            "tool_sign": "a",
                            **reference,
                        }
                    ]
                ),
            }
        )
    )

    def persist(identity, sources):
        return repository.persist_assistant_run_batch(
            message_id=identity,
            conversation_id=1,
            message_content="answer",
            terminal_status="completed",
            message_units=projection.units,
            search_records=sources,
            image_urls=[],
            skill_files=[],
            automation_proposals=[],
            user_id="owner",
            tenant_id="tenant",
        )

    persist(1, projection.search_records)
    (row,) = repository.get_source_searches_by_message(1, "owner")
    assert row["knowledge_reference"] == reference and row["source_location"] == ""
    assert row["aidp_source_reference"] == {} and row["cite_index"] == 1
    assert repository.get_source_searches_by_message(1, "foreign") == []
    invalid = [
        {
            **projection.search_records[0],
            "knowledge_reference": {"file_ref": {"file_id": "invalid"}},
        }
    ]
    from pydantic import ValidationError

    try:
        persist(2, invalid)
        raise AssertionError("Invalid source reference was committed")
    except ValidationError:
        pass
    with session_scope() as session:
        assert session.get(ConversationMessage, 2).status == "streaming"
        for model in (ConversationSourceSearch, ConversationMessageUnit):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.message_id == 2)
                )
                == 0
            )
    print(
        json.dumps(
            {
                "migration": True,
                "typed_roundtrip": True,
                "owner_guard": True,
                "rollback": True,
                "migration_sha256": hashlib.sha256(migration.read_bytes()).hexdigest(),
                "source_hashes": {
                    name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                    for name, path in {
                        "contracts.agentos_knowledge": "/opt/backend/contracts/agentos_knowledge.py",
                        "management.db.conversation.models": "/opt/backend/management/db/conversation/models.py",
                        "management.db.conversation.repository": "/opt/backend/management/db/conversation/repository.py",
                        "management.services.agent.stream": "/opt/backend/management/services/agent/stream.py",
                    }.items()
                },
            }
        )
    )
finally:
    engine.dispose()
