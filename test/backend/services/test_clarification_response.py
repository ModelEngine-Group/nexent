# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Clarification validation and atomic persistence regressions."""

import json
import sqlite3
from contextlib import contextmanager
from copy import deepcopy

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contracts.errors.exceptions import AppException
from contracts.clarification import ClarificationResponse
from management.db.conversation import repository as db

FORM = {
    'schema_version': 1,
    'questions': [
        {'id': 'text', 'type': 'text', 'title': 'Goal?'},
        {'id': 'single', 'type': 'single_choice', 'title': 'Period?', 'options': [
            {'id': 'a', 'label': 'A'}, {'id': 'b', 'label': 'B'}]},
        {'id': 'multi', 'type': 'multiple_choice', 'title': 'Metrics?', 'allow_other': True,
         'options': [{'id': 'a', 'label': 'A'}, {'id': 'b', 'label': 'B'}]},
    ],
}
RESPONSE = {
    'schema_version': 1, 'form': FORM, 'unit_index': 7,
    'answers': [
        {'questionId': 'text', 'value': 'Goal', 'otherText': None},
        {'questionId': 'single', 'value': 'b', 'otherText': None},
        {'questionId': 'multi', 'value': ['a', 'b'], 'otherText': 'Other'},
    ],
}


def test_response_preserves_choice_ids_text_and_other():
    response = ClarificationResponse.model_validate(RESPONSE).model_dump()
    assert response['answers'] == RESPONSE['answers']
    assert response['form']['questions'][0]['required'] is True
    assert response['form']['questions'][2]['allow_other'] is True


@pytest.mark.parametrize('change', [
    lambda r: r['answers'].pop(),
    lambda r: r['answers'].append(r['answers'][0]),
    lambda r: r['answers'][0].update(questionId='forged'),
    lambda r: r['answers'][0].update(value=''),
    lambda r: r['answers'][0].update(value='x' * 8001),
    lambda r: r['answers'][0].update(value=['a']),
    lambda r: r['answers'][1].update(value='forged'),
    lambda r: r['answers'][1].update(otherText='forged'),
    lambda r: r['answers'][2].update(value=['a', 'a']),
    lambda r: r['answers'][2].update(value='a'),
    lambda r: r.update(unit_index=-1),
    lambda r: r.update(schema_version=True),
    lambda r: r['form'].update(schema_version=2),
    lambda r: r['form'].update(execute='code'),
])
def test_invalid_responses_are_rejected(change):
    raw = deepcopy(RESPONSE)
    change(raw)
    with pytest.raises(ValidationError):
        ClarificationResponse.model_validate(raw)


def test_answer_length_boundary_and_other_only_selection():
    raw = deepcopy(RESPONSE)
    raw['answers'][0]['value'] = 'x' * 8000
    raw['answers'][2]['value'] = []
    assert ClarificationResponse.model_validate(raw).answers[2].otherText == 'Other'


@pytest.fixture
def storage(monkeypatch):
    dbapi = sqlite3
    if sqlite3.sqlite_version_info < (3, 35, 0):
        # Keep real transaction/RETURNING coverage on older Linux runner images.
        import pysqlite3 as dbapi
    engine = create_engine('sqlite://', module=dbapi)
    with engine.connect() as connection:
        connection.execute(text("ATTACH DATABASE ':memory:' AS nexent"))
        connection.execute(text('CREATE TABLE nexent.conversation_record_t '
                                '(conversation_id INTEGER PRIMARY KEY, created_by TEXT, delete_flag TEXT)'))
        connection.execute(text('CREATE TABLE nexent.conversation_message_t '
                                '(message_id INTEGER PRIMARY KEY, conversation_id INTEGER, message_index INTEGER, '
                                'message_role TEXT, message_source TEXT, message_content TEXT, minio_files TEXT, '
                                'opinion_flag TEXT, status TEXT, delete_flag TEXT, created_by TEXT, updated_by TEXT, '
                                'create_time DATETIME, update_time DATETIME)'))
        connection.execute(text('CREATE TABLE nexent.conversation_message_unit_t '
                                '(unit_id INTEGER PRIMARY KEY, conversation_id INTEGER, message_id INTEGER, '
                                'unit_index INTEGER, unit_type TEXT, unit_content TEXT, unit_status TEXT, '
                                'delete_flag TEXT, created_by TEXT, updated_by TEXT, '
                                'create_time DATETIME, update_time DATETIME)'))
        connection.execute(text("INSERT INTO nexent.conversation_record_t VALUES (1, 'owner', 'N')"))
        connection.execute(text("INSERT INTO nexent.conversation_message_t "
                                "(message_id,conversation_id,message_index,message_role,status,delete_flag) "
                                "VALUES (10,1,1,'assistant','completed','N')"))
        connection.execute(text('INSERT INTO nexent.conversation_message_unit_t '
                                '(message_id,conversation_id,unit_index,unit_type,unit_content,delete_flag) '
                                "VALUES (10,1,7,'human_interaction',:form,'N')"), {'form': json.dumps(FORM)})
        connection.commit()

        @contextmanager
        def sessions():
            with Session(bind=connection) as session, session.begin():
                yield session

        monkeypatch.setattr(db, 'get_db_session', sessions)
        monkeypatch.setattr(db, '_enforce_conversation_turn_limit', lambda **kwargs: None)
        monkeypatch.setattr(db, '_touch_conversation_activity', lambda *args: None)
        yield connection
    engine.dispose()


def save(response=RESPONSE, owner='owner'):
    return db.create_conversation_message({
        'conversation_id': 1, 'message_idx': 2, 'role': 'user', 'content': 'Readable answers',
        **({'clarification_response': response} if response is not None else {}),
    }, owner)


def test_user_text_and_structured_answers_commit_together(storage):
    message_id = save()
    row = storage.execute(text('SELECT message_content FROM nexent.conversation_message_t WHERE message_id=:id'),
                          {'id': message_id}).scalar_one()
    stored = json.loads(storage.execute(text('SELECT unit_content FROM nexent.conversation_message_unit_t '
                                            'WHERE message_id=:id'), {'id': message_id}).scalar_one())
    assert row == 'Readable answers'
    assert stored['source_message_id'] == 10
    assert stored['unit_index'] == 7
    assert stored['answers'] == RESPONSE['answers']


@pytest.mark.parametrize('variant', [
    'foreign', 'stale', 'wrong_unit', 'wrong_form', 'duplicate', 'other_conversation', 'deleted_form',
])
def test_invalid_source_writes_neither_user_message_nor_response(storage, variant):
    response = deepcopy(RESPONSE)
    owner = 'owner'
    if variant == 'foreign':
        owner = 'another-user'
    elif variant == 'stale':
        storage.execute(text("UPDATE nexent.conversation_message_t SET status='stopped'"))
        storage.commit()
    elif variant == 'wrong_unit':
        response['unit_index'] = 8
    elif variant == 'wrong_form':
        response['form']['questions'][0]['title'] = 'Different question'
    elif variant == 'other_conversation':
        storage.execute(text('UPDATE nexent.conversation_message_t SET conversation_id=2'))
        storage.commit()
    elif variant == 'deleted_form':
        storage.execute(text("UPDATE nexent.conversation_message_unit_t SET delete_flag='Y'"))
        storage.commit()
    else:
        save()
    before = storage.execute(text('SELECT count(*) FROM nexent.conversation_message_t')).scalar()
    storage.commit()
    with pytest.raises(AppException, match='Clarification'):
        save(response, owner)
    assert storage.execute(text('SELECT count(*) FROM nexent.conversation_message_t')).scalar() == before


def test_unit_write_failure_rolls_back_user_message(storage):
    storage.execute(text("CREATE TRIGGER nexent.fail_response BEFORE INSERT ON conversation_message_unit_t "
                         "WHEN NEW.unit_type='clarification_response' BEGIN SELECT RAISE(ABORT,'unit failed'); END"))
    storage.commit()
    with pytest.raises(IntegrityError, match='unit failed'):
        save()
    assert storage.execute(text('SELECT count(*) FROM nexent.conversation_message_t')).scalar() == 1


def test_ordinary_message_does_not_create_response(storage):
    save(None)
    assert storage.execute(text("SELECT count(*) FROM nexent.conversation_message_unit_t "
                                "WHERE unit_type='clarification_response'")).scalar() == 0


def test_missing_live_unit_index_resolves_single_matching_persisted_form(storage):
    response = {**RESPONSE, 'unit_index': None}
    message_id = save(response)
    stored = json.loads(storage.execute(text('SELECT unit_content FROM nexent.conversation_message_unit_t '
                                            'WHERE message_id=:id'), {'id': message_id}).scalar_one())
    assert stored['unit_index'] == 7
    assert stored['source_message_id'] == 10


def test_ambiguous_form_without_unit_index_is_rejected(storage):
    storage.execute(text('INSERT INTO nexent.conversation_message_unit_t '
                         '(message_id,conversation_id,unit_index,unit_type,unit_content,delete_flag) '
                         "VALUES (10,1,8,'human_interaction',:form,'N')"), {'form': json.dumps(FORM)})
    storage.commit()
    with pytest.raises(AppException, match='does not match'):
        save({**RESPONSE, 'unit_index': None})
    assert storage.execute(text('SELECT count(*) FROM nexent.conversation_message_t')).scalar() == 1


def test_agent_request_retains_structured_response():
    from contracts.agent import AgentRequest

    request = AgentRequest(query='Readable answers', conversation_id=1, clarification_response=RESPONSE)
    assert request.clarification_response.answers[1].value == 'b'
    assert request.model_dump()['clarification_response']['unit_index'] == 7


def test_service_passes_structured_answers_to_atomic_message_save(monkeypatch):
    from contracts.agent import AgentRequest
    from management.services.conversation import service

    captured = []
    monkeypatch.setattr(service, 'create_conversation_message', lambda data, *a, **kw: captured.append(data) or 20)
    request = AgentRequest(query='Readable answers', conversation_id=1, history=[],
                           clarification_response=RESPONSE)
    service.save_conversation_user(request, 'owner', 'tenant')
    assert captured[0]['content'] == 'Readable answers'
    assert captured[0]['clarification_response']['answers'] == RESPONSE['answers']


@pytest.mark.parametrize('content', [None, '{malformed', json.dumps({**RESPONSE, 'source_message_id': 10})])
def test_history_returns_structured_response_without_replacing_readable_text(monkeypatch, content):
    from management.services.conversation import service

    record = {'message_id': 20, 'message_index': 2, 'role': 'user', 'message_content': 'Readable answers',
              'status': 'completed', 'units': [] if content is None else [
                  {'unit_type': 'clarification_response', 'unit_content': content}], 'minio_files': []}
    history = {'conversation_id': 1, 'create_time': 0, 'message_records': [record],
               'search_records': [], 'image_records': []}
    monkeypatch.setattr(service, 'get_conversation_history', lambda *args: history)
    result = service.get_conversation_history_service(1, 'owner')[0]['message'][0]
    assert result['message'] == 'Readable answers'
    if content and content.startswith('{"'):
        assert result['clarification_response']['answers'] == RESPONSE['answers']
        assert result['clarification_response']['source_message_id'] == 10
    else:
        assert 'clarification_response' not in result
