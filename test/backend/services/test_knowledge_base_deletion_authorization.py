# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB-FENCE-01: only authorized cleanup can continue under a KB deletion intent."""

import pytest
from contracts.agentos_knowledge import KnowledgeAuthorizationRequest
from nexent.storage.errors import ScopeDenied

from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_authorization import setup  # noqa: F401


@pytest.mark.parametrize('action', ['upload', 'execute'])
def test_kb_deletion_revokes_new_execution_grants(setup, action):  # noqa: F811
    policy, payload, update, _, _ = setup
    update('cleanse_knowledge', deletion_request={'schema_version': 1, 'knowledge_id': 1,
                                                 'index_name': 'kb-one', 'user_id': 'user-a'})
    with pytest.raises(ScopeDenied):
        policy.authorize(payload.model_copy(update={'action': action}), context=context())


@pytest.mark.parametrize('action', ['delete', 'inspect'])
def test_delete_and_inspect_keep_current_dac_during_cleanup(setup, action):  # noqa: F811
    policy, payload, update, _, _ = setup
    update('cleanse_knowledge', deletion_request={'schema_version': 1, 'knowledge_id': 1,
                                                 'index_name': 'kb-one', 'user_id': 'user-a'})
    request = KnowledgeAuthorizationRequest(**payload.model_dump(include={'knowledge_id', 'file_id', 'file_version'}), action=action)
    assert policy.authorize(request, context=context()).action == action
    update('cleanse_memberships', delete_flag='Y')
    with pytest.raises(ScopeDenied):
        policy.authorize(request, context=context())


@pytest.mark.parametrize('edit', [True, False])
def test_resource_and_history_reads_are_denied_without_explicit_cleanup(setup, edit):  # noqa: F811
    _, payload, update, resource_policy, _ = setup
    update('cleanse_knowledge', deletion_request={'schema_version': 1, 'knowledge_id': 1,
                                                 'index_name': 'kb-one', 'user_id': 'user-a'})
    with pytest.raises(ScopeDenied):
        resource_policy.resolve_knowledge(1, edit=edit, context=context())
    with pytest.raises(ScopeDenied):
        resource_policy.resolve(payload, edit=edit, history=True, context=context())
