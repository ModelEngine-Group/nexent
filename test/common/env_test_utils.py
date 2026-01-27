"""Shared helpers for image-service related tests."""

from __future__ import annotations

import sys
import types
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any
from unittest.mock import MagicMock


def _ensure_path(path: Path) -> None:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _create_module(name: str, **attrs: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    for attr_name, attr_value in attrs.items():
        setattr(module, attr_name, attr_value)
    sys.modules[name] = module
    return module


@lru_cache(maxsize=1)
def bootstrap_env() -> Dict[str, Any]:
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parents[1]
    backend_dir = project_root / "backend"

    _ensure_path(project_root)
    _ensure_path(backend_dir)

    mock_const = MagicMock()
    consts_module = _create_module("consts", const=mock_const)
    sys.modules["consts.const"] = mock_const

    boto3_mock = MagicMock()
    sys.modules.setdefault("boto3", boto3_mock)

    client_module = _create_module(
        "backend.database.client",
        MinioClient=MagicMock(),
        PostgresClient=MagicMock(),
        db_client=MagicMock(),
        get_db_session=MagicMock(),
        as_dict=MagicMock(),
        minio_client=MagicMock(),
        postgres_client=MagicMock(),
    )
    sys.modules["database.client"] = client_module
    if "database" not in sys.modules:
        _create_module("database")

    config_utils_module = _create_module(
        "utils.config_utils",
        tenant_config_manager=MagicMock(),
        get_model_name_from_config=MagicMock(return_value=""),
    )

    nexent_module = _create_module("nexent", MessageObserver=MagicMock())
    _create_module("nexent.core")
    _create_module("nexent.core.models", OpenAIVLModel=MagicMock())

    return {
        "mock_const": mock_const,
        "consts_module": consts_module,
        "client_module": client_module,
        "config_utils_module": config_utils_module,
        "nexent_module": nexent_module,
        "boto3_mock": boto3_mock,
        "project_root": project_root,
        "backend_dir": backend_dir,
    }