"""
Test package for SDK modules.
"""

import sys
import types


fake_unstructured = types.ModuleType("unstructured_inference")
fake_models = types.ModuleType("unstructured_inference.models")
fake_tables = types.ModuleType("unstructured_inference.models.tables")
fake_tables.tables_agent = types.SimpleNamespace(model=None)
fake_logger = types.ModuleType("unstructured_inference.logger")
fake_logger.logger = types.SimpleNamespace(
    info=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    error=lambda *a, **k: None,
)
fake_models.tables = fake_tables
fake_unstructured.models = fake_models
sys.modules.setdefault("unstructured_inference", fake_unstructured)
sys.modules.setdefault("unstructured_inference.models", fake_models)
sys.modules.setdefault("unstructured_inference.models.tables", fake_tables)
sys.modules.setdefault("unstructured_inference.logger", fake_logger)
