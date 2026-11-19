# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared lightweight database stubs for isolated database unit tests."""

import sys
import types
from unittest.mock import MagicMock


class FakeColumn:
    """Minimal column proxy for SQLAlchemy-style test expressions."""

    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return ("eq", self.name, other)

    def __hash__(self):
        return hash(self.name)

    def desc(self):
        return ("desc", self.name)


def install_database_stubs(model_name, model_class):
    """Register the client and model modules required by an isolated DB test."""
    client_module = types.ModuleType("infrastructure.rdb.client")
    client_module.get_db_session = MagicMock(name="get_db_session")
    client_module.filter_property = MagicMock(
        name="filter_property", side_effect=lambda data, _model: data
    )
    sys.modules["infrastructure.rdb.client"] = client_module
    sys.modules["infrastructure.object_storage.client"] = sys.modules["infrastructure.rdb.client"]
    from test.common.database_stubs import install_serialization_stub
    install_serialization_stub(sys.modules["infrastructure.rdb.client"])
    from test.common.database_stubs import install_serialization_stub
    install_serialization_stub(sys.modules["infrastructure.rdb.client"])
    sys.modules["infrastructure.rdb.client"] = client_module
    sys.modules["infrastructure.object_storage.client"] = sys.modules["infrastructure.rdb.client"]
    from test.common.database_stubs import install_serialization_stub
    install_serialization_stub(sys.modules["infrastructure.rdb.client"])

    models_module = types.ModuleType("management.db.models")
    setattr(models_module, model_name, model_class)
    sys.modules["management.db.models"] = models_module
    sys.modules["management.db.models"] = models_module
