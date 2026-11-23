# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Build and exercise isolated verification images without replacing services."""

import hashlib
import json
import re
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

MODULES = {
    "nexent.core.agents.nexent_agent": "core/agents/nexent_agent.py",
    "nexent.core.agents.agent_model": "core/agents/agent_model.py",
    "nexent.core.agents.subagent_wrapper": "core/agents/subagent_wrapper.py",
    "nexent.core.agents.sandbox": "core/agents/sandbox.py",
    "nexent.core.concurrency.cancellation": "core/concurrency/cancellation.py",
}


def _diagnostic_summary(output):
    """Allow only structural traceback data; kernel output can contain secrets."""
    frames = re.findall(r'File "([^"\n]+)", line (\d+), in ([\w<>]+)', output)
    return {
        "frames": [{"file": Path(path).name, "line": int(line), "function": function}
                   for path, line, function in frames[-12:]],
        "exception_types": re.findall(r'^([A-Za-z_][\w.]*(?:Error|Exception))(?::|$)', output, re.MULTILINE)[-8:],
        "errno": re.findall(r'\[Errno (\d+)\]', output)[-8:],
        "characters": len(output),
    }


def command(arguments, *, diagnostics=None, **kwargs):
    started = time.monotonic()
    try:
        completed = subprocess.run(arguments, text=True, encoding="utf-8", errors="replace",
                                   capture_output=True, timeout=900, check=False, **kwargs)
    except subprocess.TimeoutExpired:
        if diagnostics is not None:
            diagnostics.write_text(json.dumps({"status": "TIMEOUT", "timeout_seconds": 900,
                "duration_seconds": round(time.monotonic() - started, 3)}), encoding="utf-8")
        raise
    summary = {"exit_code": completed.returncode,
               "duration_seconds": round(time.monotonic() - started, 3),
               "stdout": _diagnostic_summary(completed.stdout),
               "stderr": _diagnostic_summary(completed.stderr)}
    if diagnostics is not None:
        diagnostics.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    # Do not persist raw bridge output, source lines, or exception messages.
    if completed.returncode:
        exit_code = completed.returncode
        # Pytest can serialize failing-frame locals into JUnit; do not leave
        # the raw CompletedProcess (including bridge credentials) in that frame.
        del completed
        raise AssertionError(f"SAI Docker operation {arguments[:2]} failed with exit "
                             f"{exit_code}; structural diagnostics: {summary}")
    return completed.stdout.strip()


@contextmanager
def verification_image(repo: Path):
    base = command(["docker", "image", "inspect", "nexent/nexent:latest", "--format", "{{.Id}}"])
    sandbox = command(["docker", "image", "inspect", "nexent/nexent-sandbox:latest", "--format", "{{.Id}}"])
    image = None
    with tempfile.TemporaryDirectory(prefix="nexent-sai-image-") as scratch:
        definition = Path(scratch) / "Dockerfile"
        definition.write_text(
            "FROM nexent/nexent:latest\n"
            "COPY nexent/ /opt/backend/.venv/lib/python3.11/site-packages/nexent/\n"
            f"LABEL nexent.sai.verification={uuid.uuid4().hex}\n",
            encoding="utf-8",
        )
        image = command(["docker", "build", "--pull=false", "--quiet", "-f", str(definition), str(repo / "sdk")])
        try:
            assert command(["docker", "image", "inspect", "nexent/nexent:latest", "--format", "{{.Id}}"] ) == base
            yield {"runtime_image": image.splitlines()[-1], "sandbox_image": sandbox}
        finally:
            # Remove only the untagged verification image, never the base image.
            command(["docker", "image", "rm", image.splitlines()[-1]])


def execute_probe(repo: Path, image: dict, evidence: Path, scope: str, batches: int):
    evidence.mkdir(parents=True, exist_ok=True)
    fingerprints = {name: hashlib.sha256((repo / "sdk/nexent" / path).read_bytes()).hexdigest()
                    for name, path in MODULES.items()}
    (evidence / "expected-sources.json").write_text(json.dumps(fingerprints), encoding="utf-8")
    helper = Path(__file__).with_name("sai_kernel_probe.py").resolve()
    # Precreate a host-owned file. The container truncates it without changing
    # ownership; preserve this raw result instead of overwriting it on the host.
    raw_result = evidence / f"probe-{uuid.uuid4().hex}.json"
    with raw_result.open("x", encoding="utf-8"):
        pass
    command([
        "docker", "run", "--rm", "--entrypoint", "/opt/backend/.venv/bin/python",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", f"{helper.as_posix()}:/tests/probe.py:ro",
        "-v", f"{evidence.resolve().as_posix()}:/evidence",
        image["runtime_image"], "/tests/probe.py", "--batches", str(batches), "--scope", scope,
        "--expected-sources", "/evidence/expected-sources.json", "--output", f"/evidence/{raw_result.name}",
    ], diagnostics=evidence / "docker-run.json")
    result = json.loads(raw_result.read_text(encoding="utf-8"))
    result["images"] = image
    # Replace, rather than truncate, a summary left by an older root-owned run.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=evidence, delete=False) as summary:
        json.dump(result, summary, indent=2)
    Path(summary.name).replace(evidence / "result.json")
    return result
