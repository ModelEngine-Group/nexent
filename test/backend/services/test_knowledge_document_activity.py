# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Document appends retain the existing automatic-summary activity timestamp."""

import pytest
from nexent.storage.errors import ScopeDenied

from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_summary_schedule import (
    isolated_connections as isolated_connections,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_summary_schedule import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_summary_schedule import (
    setup as setup,  # noqa: PLC0414
)


def test_document_activity_touches_timestamp_without_enabling_a_schedule(setup):
    journal, _, _, _, _ = setup
    before = journal.record(1, context=context())
    after = journal.touch_documents(1, context=context())
    assert after["last_doc_update_time"] is not None and after["last_doc_update_time"] != before["last_doc_update_time"]
    assert after["summary_schedule"] == before["summary_schedule"]
    assert after["summary_frequency"] == before["summary_frequency"]
    assert after["updated_by"] == "user-a"


def test_document_activity_revocation_rolls_back_the_timestamp_and_version(setup):
    journal, _, update, _, _ = setup
    before = journal.record(1, context=context())
    update("cleanse_memberships", delete_flag="Y")
    with pytest.raises(ScopeDenied):
        journal.touch_documents(1, context=context())
    after = journal.record(1, context=context())
    assert after["last_doc_update_time"] == before["last_doc_update_time"] and after["version"] == before["version"]
