# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise the production request model and route without external services."""
import ast
from pathlib import Path
from typing import List, Optional
import unittest
from unittest.mock import Mock
from unittest.mock import patch
from urllib.parse import urlsplit, urlunsplit
import os

from fastapi import FastAPI, Header, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parents[4]




class ProxyAddressTests(unittest.TestCase):
    def test_browser_locale_removed_without_losing_deployment_prefix(self):
        source = ROOT / "test-e2e/cases/API-AUTO-8CFB0598A62F2E58/test.py"
        function = next(n for n in ast.parse(source.read_text(encoding="utf-8")).body
                        if isinstance(n, ast.FunctionDef) and n.name == "_frontend_api_base")
        for base, expected in (
            ("http://localhost:3000/zh", "http://localhost:3000"),
            ("http://localhost:3000/nexent/zh", "http://localhost:3000/nexent"),
            ("http://localhost:3000/nexent", "http://localhost:3000/nexent"),
        ):
            namespace = {"os": os, "urlsplit": urlsplit, "urlunsplit": urlunsplit,
                         "load_yaml": lambda _: {"base_url": base, "locale": "zh-CN"},
                         "AutomationInfrastructureError": RuntimeError}
            exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(namespace[function.name](), expected)
