# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise the real OPS bootstrap audit in isolated child interpreters."""
import ast
from pathlib import Path
import subprocess
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[3] / "cases/OPS-BOOTSTRAP-D5-001/test.py"


def installed_guard():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    bootstrap = next(node.value.value for node in ast.walk(tree)
                     if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                     and any(isinstance(target, ast.Name) and target.id == "bootstrap" for target in node.targets))
    tree = ast.parse(bootstrap)
    # Install the actual guard without launching the production HTTP process.
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "run_path")]
    return ast.unparse(tree)


def test_standard_library_socketpair_remains_usable_for_event_loop():
    command = installed_guard() + "\nimport socket\na, b = socket.socketpair()\na.close()\nb.close()\n"
    result = subprocess.run([sys.executable, "-c", command], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("action,message", [
    ("import socket; s=socket.socket(); s.settimeout(0.05); s.connect(('127.0.0.1', 9))", "Forbidden outbound connection"),
    ("import socket; s=socket.socket(); s.settimeout(0.05); s.connect(('192.0.2.1', 9))", "Forbidden outbound connection"),
    ("import redis", "Forbidden business import"),
    ("import subprocess; subprocess.run([sys.executable, '-c', 'pass'])", "Forbidden child command"),
])
def test_business_operations_are_still_forbidden(action, message):
    command = installed_guard() + "\n" + action
    result = subprocess.run([sys.executable, "-c", command], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and message in result.stderr
