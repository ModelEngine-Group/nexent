# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Ops image whitelist parity: the ops import graph stays inside the COPY set.

The ops container ships a curated module whitelist
(deploy/images/dockerfiles/ops/Dockerfile). A new import of a management-only
module compiles locally — the repository tree is complete — but crashes the
container at startup with an ImportError. This test runs the ops entrypoint
import graph in a clean subprocess (including the modules the /nb mirror
imports lazily) and requires every imported repository module to be covered
by a COPY instruction.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "deploy" / "images" / "dockerfiles" / "ops" / "Dockerfile"
BACKSLASH = chr(92)

# The subprocess keeps the graph clean: the in-process sys.modules of a
# shared pytest run is polluted by every other test's imports.
_GRAPH_PROBE = """
import json, sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "backend"))
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "sdk"))

import backend.http.ops_service
import backend.http.server.northbound
import management.services.permission.identity.northbound
import ops.api.monitoring
import ops.api.northbound_envelope
import ops.api.northbound_gates

shipped = set(json.loads(sys.argv[2]))
excluded = ("test/", "test-e2e/", "scripts/", "deploy/", "doc/", "docs/", "frontend/")
missing = []
for name, module in sorted(sys.modules.items()):
    file = getattr(module, "__file__", None)
    if not file or "<stdin>" in str(file):
        continue
    try:
        relative = Path(file).resolve().relative_to(root).as_posix()
    except ValueError:
        continue
    if ".venv" in relative or "/site-packages/" in relative or relative.startswith(excluded):
        continue
    if relative not in shipped:
        missing.append(f"{name} -> {relative}")
print(json.dumps(missing))
"""


def _shipped_python_files() -> set:
    """Every repository .py file the ops Dockerfile copies into the image."""
    text = DOCKERFILE.read_text(encoding="utf-8").replace("\r\n", "\n")
    text = text.replace(BACKSLASH + "\n", " ")  # join COPY continuation lines
    shipped: set = set()
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("COPY "):
            continue
        for source in line.split()[1:-1]:  # the last token is the destination
            path = ROOT / source
            if path.is_dir():
                shipped.update(p.relative_to(ROOT).as_posix() for p in path.rglob("*.py"))
            elif path.is_file() and source.endswith(".py"):
                shipped.add(source)
    return shipped


def test_ops_entrypoint_import_graph_stays_inside_the_image_whitelist():
    shipped = _shipped_python_files()
    assert shipped, "the ops Dockerfile must ship Python sources"

    result = subprocess.run(
        [sys.executable, "-I", "-c", _GRAPH_PROBE, str(ROOT), json.dumps(sorted(shipped))],
        capture_output=True, text=True, cwd=ROOT, timeout=300,
    )
    assert result.returncode == 0, f"import probe failed:\n{result.stderr}"
    missing = json.loads(result.stdout.strip().splitlines()[-1])
    assert not missing, (
        "modules imported by the ops service are missing from the ops image "
        "whitelist (the container would crash at startup):\n" + "\n".join(missing)
    )
