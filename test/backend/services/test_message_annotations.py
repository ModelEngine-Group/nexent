# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Structured reply annotations: contracts, persistence and history merging."""

import importlib
import json
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from contracts.annotations import (
    ANNOTATION_COMMENT_MAX_CHARS,
    ANNOTATION_MAX_COUNT,
    ANNOTATION_QUOTED_TEXT_MAX_CHARS,
    ANNOTATION_SOURCE_EXCERPT_MAX_CHARS,
    format_annotations_for_llm,
    normalize_message_annotations,
    parse_message_annotation_unit,
)
from contracts.agent import AgentRequest

ANNOTATION = {
    'quoted_text': 'quoted reply text',
    'comment': 'note',
    'source_excerpt': 'reply intro',
}


def test_normalize_validates_trims_and_drops_unusable_entries():
    annotations = normalize_message_annotations([
        ANNOTATION,
        {'quoted_text': '   '},
        {'quoted_text': ''},
        {'comment': 'no quote'},
        'not-a-dict',
        {'quoted_text': 'keep', 'comment': '   ', 'source_excerpt': '  '},
    ])

    assert annotations is not None
    assert [item.quoted_text for item in annotations] == [
        'quoted reply text', 'keep',
    ]
    assert annotations[1].comment is None
    assert annotations[1].source_excerpt is None


@pytest.mark.parametrize('raw', [None, 'text', {}, 42])
def test_normalize_rejects_non_list_payloads(raw):
    assert normalize_message_annotations(raw) is None


def test_normalize_returns_none_when_nothing_usable_remains():
    assert normalize_message_annotations([{'quoted_text': ' '}]) is None


def test_normalize_applies_defensive_caps():
    oversized = {
        'quoted_text': 'q' * (ANNOTATION_QUOTED_TEXT_MAX_CHARS + 10),
        'comment': 'c' * (ANNOTATION_COMMENT_MAX_CHARS + 10),
        'source_excerpt': 's' * (ANNOTATION_SOURCE_EXCERPT_MAX_CHARS + 10),
    }

    truncated = normalize_message_annotations([oversized])

    assert truncated is not None
    assert len(truncated[0].quoted_text) == ANNOTATION_QUOTED_TEXT_MAX_CHARS
    assert len(truncated[0].comment) == ANNOTATION_COMMENT_MAX_CHARS
    assert len(truncated[0].source_excerpt) == ANNOTATION_SOURCE_EXCERPT_MAX_CHARS

    many = [dict(oversized, quoted_text=f'quote {index}')
            for index in range(ANNOTATION_MAX_COUNT + 3)]
    capped = normalize_message_annotations(many)

    assert capped is not None
    assert len(capped) == ANNOTATION_MAX_COUNT


def test_format_without_annotations_returns_text_unchanged():
    assert format_annotations_for_llm('why stop?', None) == 'why stop?'
    assert format_annotations_for_llm('why stop?', []) == 'why stop?'


def test_format_merges_blocks_comment_and_source_into_user_text():
    annotations = normalize_message_annotations([
        {'quoted_text': 'line one\nline two', 'comment': 'skip this',
         'source_excerpt': 'reply intro'},
    ])

    merged = format_annotations_for_llm('why stop?', annotations)

    assert merged == ('1. Quote (from reply "reply intro"):\n'
                      '> line one\n> line two\n'
                      'Comment: skip this\n\n---\n\nwhy stop?')


def test_format_joins_multiple_blocks_and_skips_empty_fields():
    annotations = normalize_message_annotations([
        {'quoted_text': 'first', 'comment': 'note'},
        {'quoted_text': 'second'},
    ])

    merged = format_annotations_for_llm('follow-up', annotations)

    assert merged == ('1. Quote:\n> first\nComment: note\n\n'
                      '2. Quote:\n> second\n\n---\n\nfollow-up')


def test_format_annotation_only_send_keeps_blocks_without_separator():
    annotations = normalize_message_annotations([{'quoted_text': 'only quote'}])

    assert format_annotations_for_llm('', annotations) == '1. Quote:\n> only quote'


def test_parse_unit_round_trips_and_rejects_invalid_payloads():
    annotations = normalize_message_annotations([ANNOTATION])
    payload = json.dumps([item.model_dump(mode='json') for item in annotations])

    parsed = parse_message_annotation_unit(payload)
    assert parsed is not None and len(parsed) == 1
    assert parsed[0].quoted_text == 'quoted reply text'

    assert parse_message_annotation_unit(None) is None
    assert parse_message_annotation_unit('{malformed') is None
    assert parse_message_annotation_unit(json.dumps([{'quoted_text': ''}])) is None


def test_agent_request_retains_structured_annotations():
    request = AgentRequest(query='why stop?', conversation_id=1, annotations=[ANNOTATION])

    assert request.annotations[0].comment == 'note'
    dumped = request.model_dump()
    assert dumped['annotations'][0]['source_excerpt'] == 'reply intro'


def test_service_passes_annotations_to_atomic_message_save(monkeypatch):
    from management.services.conversation import service

    captured = []
    monkeypatch.setattr(
        service, 'create_conversation_message',
        lambda data, *args, **kwargs: captured.append(data) or 20,
    )
    request = AgentRequest(query='why stop?', conversation_id=1, history=[],
                           annotations=[ANNOTATION, {'quoted_text': ' '}])
    service.save_conversation_user(request, 'owner', 'tenant')

    assert captured[0]['content'] == 'why stop?'
    # The unusable second entry is dropped by normalization.
    assert captured[0]['annotations'] == [ANNOTATION]


def test_history_returns_annotations_without_replacing_readable_text(monkeypatch):
    from management.services.conversation import service

    annotations = normalize_message_annotations([ANNOTATION])
    payload = json.dumps([item.model_dump(mode='json') for item in annotations])
    record = {'message_id': 20, 'message_index': 2, 'role': 'user',
              'message_content': 'why stop?', 'status': 'completed',
              'units': [
                  {'unit_type': 'message_annotations', 'unit_content': payload},
                  {'unit_type': 'message_annotations', 'unit_content': '{bad'},
              ],
              'minio_files': []}
    history = {'conversation_id': 1, 'create_time': 0, 'message_records': [record],
               'search_records': [], 'image_records': []}
    monkeypatch.setattr(service, 'get_conversation_history', lambda *args: history)

    item = service.get_conversation_history_service(1, 'owner')[0]['message'][0]

    assert item['message'] == 'why stop?'
    assert item['annotations'] == [ANNOTATION]


@pytest.fixture
def message_db(monkeypatch):
    monkeypatch.setattr(
        'nexent.storage.storage_client_factory.create_storage_client_from_config',
        lambda *_: MagicMock(),
    )
    module = importlib.import_module('management.db.conversation.repository')
    engine = create_engine('sqlite://', poolclass=StaticPool)
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS nexent")
        connection.exec_driver_sql(
            'CREATE TABLE nexent.conversation_record_t '
            '(conversation_id INTEGER PRIMARY KEY, created_by TEXT, delete_flag TEXT)')
        connection.exec_driver_sql(
            'CREATE TABLE nexent.conversation_message_t '
            '(message_id INTEGER PRIMARY KEY, conversation_id INTEGER, message_index INTEGER, '
            'message_role TEXT, message_source TEXT, message_content TEXT, minio_files TEXT, '
            'opinion_flag TEXT, status TEXT, delete_flag TEXT, created_by TEXT, updated_by TEXT, '
            'create_time DATETIME, update_time DATETIME)')
        connection.exec_driver_sql(
            'CREATE TABLE nexent.conversation_message_unit_t '
            '(unit_id INTEGER PRIMARY KEY, conversation_id INTEGER, message_id INTEGER, '
            'unit_index INTEGER, unit_type TEXT, unit_content TEXT, unit_status TEXT, '
            'delete_flag TEXT, created_by TEXT, updated_by TEXT, create_time DATETIME, '
            'update_time DATETIME)')
        connection.exec_driver_sql("INSERT INTO nexent.conversation_record_t VALUES (1, 'owner', 'N')")

    monkeypatch.setattr(module, 'get_db_session',
                        _session_factory(engine))
    monkeypatch.setattr(module, '_get_user_tenant', lambda _: {'tenant_id': 'tenant'})
    monkeypatch.setattr(module, '_enforce_conversation_turn_limit', lambda **kwargs: None)
    monkeypatch.setattr(module, '_touch_conversation_activity', lambda *args: None)

    def insert_message(message_id, index, role, content, status='completed', deleted='N'):
        with engine.begin() as connection:
            connection.execute(text(
                'INSERT INTO nexent.conversation_message_t '
                '(message_id, conversation_id, message_index, message_role, '
                'message_content, status, delete_flag) '
                'VALUES (:id, 1, :idx, :role, :body, :status, :deleted)'),
                {'id': message_id, 'idx': index, 'role': role, 'body': content,
                 'status': status, 'deleted': deleted})

    def insert_unit(unit_id, message_id, unit_type, content, status='completed', deleted='N'):
        with engine.begin() as connection:
            connection.execute(text(
                'INSERT INTO nexent.conversation_message_unit_t '
                '(unit_id, message_id, conversation_id, unit_index, unit_type, '
                'unit_content, unit_status, delete_flag) '
                'VALUES (:id, :mid, 1, :idx, :kind, :body, :status, :deleted)'),
                {'id': unit_id, 'mid': message_id, 'idx': unit_id, 'kind': unit_type,
                 'body': content, 'status': status, 'deleted': deleted})

    yield module, insert_message, insert_unit, engine
    engine.dispose()


def _session_factory(engine):
    @contextmanager
    def session():
        with Session(engine) as current, current.begin():
            yield current

    return session


def test_create_message_persists_annotations_as_structured_unit(message_db):
    module, _, _, engine = message_db

    message_id = module.create_conversation_message({
        'conversation_id': 1, 'message_idx': 0, 'role': 'user',
        'content': 'why stop?', 'annotations': [ANNOTATION],
    }, 'owner')

    with engine.begin() as connection:
        rows = connection.execute(text(
            'SELECT unit_type, unit_content FROM nexent.conversation_message_unit_t '
            'WHERE message_id = :mid'), {'mid': message_id}).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 'message_annotations'
    assert json.loads(rows[0][1]) == [ANNOTATION]


def test_create_message_skips_annotation_unit_for_assistant_rows(message_db):
    module, _, _, engine = message_db

    message_id = module.create_conversation_message({
        'conversation_id': 1, 'message_idx': 1, 'role': 'assistant',
        'content': 'answer', 'annotations': [ANNOTATION],
    }, 'owner')

    with engine.begin() as connection:
        count = connection.execute(text(
            'SELECT COUNT(*) FROM nexent.conversation_message_unit_t '
            'WHERE message_id = :mid'), {'mid': message_id}).scalar()
    assert count == 0


def test_historical_turns_merge_annotations_into_model_facing_text(message_db):
    module, insert_message, insert_unit, _ = message_db
    annotations = normalize_message_annotations([ANNOTATION])
    payload = json.dumps([item.model_dump(mode='json') for item in annotations])

    insert_message(1, 0, 'user', 'why stop?')
    insert_message(2, 1, 'assistant', 'because of the quota')
    insert_unit(1, 1, 'message_annotations', payload)
    insert_message(3, 2, 'user', 'then raise it')

    turns = module.get_historical_context(1, 3, 'owner', 'tenant')['conversation_turns']

    assert len(turns) == 1
    assert turns[0]['user_message'] == (
        '1. Quote (from reply "reply intro"):\n'
        '> quoted reply text\n'
        'Comment: note\n\n---\n\nwhy stop?'
    )
    assert turns[0]['assistant_final_answer'] == 'because of the quota'


def test_historical_turns_ignore_deleted_annotation_units(message_db):
    module, insert_message, insert_unit, _ = message_db
    insert_message(1, 0, 'user', 'why stop?')
    insert_message(2, 1, 'assistant', 'because of the quota')
    insert_unit(1, 1, 'message_annotations', json.dumps([ANNOTATION]), deleted='Y')
    insert_message(3, 2, 'user', 'then raise it')

    turns = module.get_historical_context(1, 3, 'owner', 'tenant')['conversation_turns']

    assert turns[0]['user_message'] == 'why stop?'
