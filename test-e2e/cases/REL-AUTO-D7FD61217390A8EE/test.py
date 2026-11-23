from __future__ import annotations

import logging
from datetime import datetime

import pytest
from sqlalchemy import delete, insert, select

from database.client import get_db_session
from database.db_models import ModelRecord
from database.model_management_db import fail_detecting_models_on_startup

CASE_ID = 'REL-AUTO-D7FD61217390A8EE'
TENANT_ID = 'rel_auto_d7fd61217390a8ee_test'
OLD_TIMESTAMP = datetime(2000, 1, 1, 0, 0, 0)


def _model_name(key):
    return 'rel_auto_d7fd61217390a8ee_' + key


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D5')
def test_rel_auto_d7fd61217390a8ee_fail_detecting_models_on_startup(caplog):
    records = {
        'A1': ('detecting', 'N'),
        'A2': ('detecting', 'N'),
        'B': ('detecting', 'Y'),
        'C1': ('available', 'N'),
        'C2': ('unavailable', 'N'),
        'C3': ('not_detected', 'N'),
    }

    logger = logging.getLogger('database.model_management_db')
    caplog.set_level(logging.DEBUG, logger=logger.name)

    def clear(session):
        session.execute(
            delete(ModelRecord).where(ModelRecord.tenant_id == TENANT_ID)
        )

    try:
        with get_db_session() as session:
            clear(session)
            for key, (status, flag) in records.items():
                session.execute(
                    insert(ModelRecord).values(
                        model_name=_model_name(key),
                        tenant_id=TENANT_ID,
                        connect_status=status,
                        delete_flag=flag,
                        update_time=OLD_TIMESTAMP,
                    )
                )

        caplog.clear()
        rowcount = fail_detecting_models_on_startup()

        with get_db_session() as session:
            rows = {
                row.model_name: (row.connect_status, row.update_time)
                for row in session.execute(
                    select(ModelRecord).where(ModelRecord.tenant_id == TENANT_ID)
                )
                .scalars()
                .all()
            }

        assert rowcount == 2

        for key in ('A1', 'A2'):
            status, update_time = rows[_model_name(key)]
            assert status == 'unavailable'
            assert update_time is not None
            assert update_time > OLD_TIMESTAMP

        for key, (original_status, _flag) in records.items():
            if key in ('A1', 'A2'):
                continue
            status, update_time = rows[_model_name(key)]
            assert status == original_status
            assert update_time == OLD_TIMESTAMP

        assert fail_detecting_models_on_startup() == 0

        log_text = '\n'.join(record.getMessage() for record in caplog.records)
        lowered = log_text.lower()
        assert 'api_key' not in lowered
        assert 'access_token' not in lowered
        assert not any(record.levelno >= logging.ERROR for record in caplog.records)
    finally:
        with get_db_session() as session:
            clear(session)