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


class PromptValidationTests(unittest.TestCase):
    def setUp(self):
        model_source = ROOT / "backend/consts/model.py"
        model_node = next(n for n in ast.parse(model_source.read_text(encoding="utf-8")).body
                          if isinstance(n, ast.ClassDef) and n.name == "GeneratePromptRequest")
        namespace = {"BaseModel": BaseModel, "Field": Field, "field_validator": field_validator,
                     "Optional": Optional, "List": List}
        exec(compile(ast.Module(body=[model_node], type_ignores=[]), str(model_source), "exec"), namespace)
        self.generation = Mock(return_value=iter(['data: {"success": true}\n\n']))
        self.identity = Mock(return_value=("fixture-user", "fixture-tenant", "en"))
        namespace.update({"Header": Header, "Request": Request, "StreamingResponse": StreamingResponse,
                          "get_current_user_info": self.identity,
                          "gen_system_prompt_streamable": self.generation,
                          "logger": Mock()})
        route_source = ROOT / "backend/apps/prompt_app.py"
        route = next(n for n in ast.parse(route_source.read_text(encoding="utf-8")).body
                     if isinstance(n, ast.AsyncFunctionDef) and n.name == "generate_and_save_system_prompt_api")
        route.decorator_list = []
        exec(compile(ast.Module(body=[route], type_ignores=[]), str(route_source), "exec"), namespace)
        app = FastAPI()
        app.post("/prompt/generate")(namespace[route.name])
        self.client = TestClient(app)

    def test_blank_rejected_before_identity_or_generation(self):
        for text in ("", " \t\r\n", "\u3000"):
            with self.subTest(text=repr(text)):
                result = self.client.post("/prompt/generate", json={
                    "task_description": text, "agent_id": 1, "model_id": 1,
                })
                self.assertEqual(result.status_code, 422)
                self.assertNotIn("text/event-stream", result.headers.get("content-type", ""))
                self.assertEqual(result.json()["detail"][0]["loc"], ["body", "task_description"])
        self.identity.assert_not_called()
        self.generation.assert_not_called()

    def test_valid_input_preserves_content_and_streaming(self):
        result = self.client.post("/prompt/generate", json={
            "task_description": "  Answer questions  ", "agent_id": 1, "model_id": 1,
        })
        self.assertEqual(result.status_code, 200)
        self.assertIn("text/event-stream", result.headers["content-type"])
        self.assertIn('"success": true', result.text)
        self.assertEqual(self.generation.call_args.kwargs["task_description"], "  Answer questions  ")


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
