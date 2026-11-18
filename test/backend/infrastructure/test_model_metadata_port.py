# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Model catalog ports cannot select credentials or run with Management scope."""

from time import monotonic
from unittest.mock import Mock

import pytest
from nexent.storage.errors import InvalidInput, ScopeDenied
from nexent.storage.models import (
    OperationContext,
    PageRequest,
    RecordQuery,
    StorageScope,
)

from infrastructure.rdb.model_metadata import DATASET, bind_model_metadata


@pytest.mark.parametrize("role,fields", [("runtime", ("api_key",)), ("management", ())])
def test_catalog_rejects_privileged_fields_and_wrong_role_before_connection(role, fields):
    engine = Mock()
    engine.dialect.name = "postgresql"
    with pytest.raises((ScopeDenied, InvalidInput)):
        port = bind_model_metadata(StorageScope(role, "tenant", "user", {DATASET}), engine)
        assert not {"api_key", "http_headers", "base_url"} & set(port._tables[DATASET].c.keys())
        port.query(DATASET, RecordQuery(fields=fields), PageRequest(), context=OperationContext("query", monotonic() + 5))
    engine.connect.assert_not_called()


def test_metadata_projection_keeps_configured_dimension_as_a_nullable_integer():
    engine = Mock(); engine.dialect.name = 'postgresql'
    port = bind_model_metadata(StorageScope('runtime', 'tenant', 'user', {DATASET}), engine)
    assert 'max_tokens' in port._tables[DATASET].c
    assert not {'api_key', 'http_headers', 'base_url', 'access_token'} & set(port._tables[DATASET].c.keys())
    engine.connect.assert_not_called()
