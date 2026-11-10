# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Run isolated repository proofs in the configured local backend environment."""

import json
import os
from pathlib import Path
import subprocess
import uuid


def run_backend_scenario(scenario: str) -> None:
    home = Path(os.environ["NEXENT_TEST_HOME"])
    configuration = json.loads((home / "config" / "resource-center.json").read_text(encoding="utf-8"))
    required = {"backend_container", "backend_directory", "python", "database_container"}
    if set(configuration) != required or any(not isinstance(configuration[key], str) or not configuration[key].strip() for key in required):
        raise ValueError("Invalid resource-center configuration; use infra/config/resource-center.schema.json")
    directory = Path(__file__).resolve().parents[1] / "resource_center"
    remote = "/tmp/rsc_contract_" + uuid.uuid4().hex
    container = configuration["backend_container"]
    copied = subprocess.run(["docker", "cp", str(directory), f"{container}:{remote}"], capture_output=True, text=True)
    assert copied.returncode == 0, copied.stderr
    try:
        result = subprocess.run([
            "docker", "exec", "-e", f"PYTHONPATH={configuration['backend_directory']}", "-w", configuration["backend_directory"],
            container, configuration["python"], remote + "/backend_scenarios.py", scenario,
        ], capture_output=True, text=True, encoding="utf-8", timeout=240)
        assert result.returncode == 0, f"Isolated backend scenario failed:\n{result.stdout}\n{result.stderr}"
    finally:
        subprocess.run(["docker", "exec", container, "rm", "-rf", remote], check=True, capture_output=True)
