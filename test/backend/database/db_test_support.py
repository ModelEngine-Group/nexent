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
    client_module = types.ModuleType("database.client")
    client_module.get_db_session = MagicMock(name="get_db_session")
    client_module.filter_property = MagicMock(
        name="filter_property", side_effect=lambda data, _model: data
    )
    sys.modules["database.client"] = client_module
    sys.modules["backend.database.client"] = client_module

    models_module = types.ModuleType("database.db_models")
    setattr(models_module, model_name, model_class)
    sys.modules["database.db_models"] = models_module
    sys.modules["backend.database.db_models"] = models_module
