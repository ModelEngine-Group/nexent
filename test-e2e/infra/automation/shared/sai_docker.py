"""Build and exercise isolated verification images without replacing services."""

import hashlib
import json
import subprocess
import tempfile
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


def command(arguments, **kwargs):
    completed = subprocess.run(arguments, text=True, encoding="utf-8", errors="replace",
                               capture_output=True, timeout=900, check=False, **kwargs)
    # Kernel bridge diagnostics may include credentials. Never reproduce raw output.
    if completed.returncode:
        raise AssertionError(f"SAI Docker operation {arguments[:2]} failed with exit {completed.returncode}")
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
    command([
        "docker", "run", "--rm", "--entrypoint", "/opt/backend/.venv/bin/python",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", f"{helper.as_posix()}:/tests/probe.py:ro",
        "-v", f"{evidence.resolve().as_posix()}:/evidence",
        image["runtime_image"], "/tests/probe.py", "--batches", str(batches), "--scope", scope,
        "--expected-sources", "/evidence/expected-sources.json", "--output", "/evidence/result.json",
    ])
    result = json.loads((evidence / "result.json").read_text(encoding="utf-8"))
    result["images"] = image
    (evidence / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
