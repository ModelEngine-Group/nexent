#!/usr/bin/env python3
"""Run a secret-safe real-model probe through Nexent's production SDK model."""

import json
import os
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, "/opt/sdk")
sys.path.insert(0, "/opt/backend")

from nexent.core.models.openai_llm import OpenAIModel
from nexent.core.utils.observer import MessageObserver


def load_env(path: Path) -> dict[str, str]:
    values = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def run_probe() -> dict:
    credential_dir = Path(os.environ.get("NEXENT_RUNTIME_CREDENTIAL_DIR", "/runtime-credentials"))
    config = yaml.safe_load((credential_dir / "models.yaml").read_text(encoding="utf-8"))
    secrets = load_env(credential_dir / "secrets.env")
    llm = next(
        model for model in config["models"]
        if str(model.get("capability", "")).lower() == "llm"
    )
    secret_name = str(llm["secret_env_key"])
    api_key = secrets.get(secret_name, "")
    if not api_key:
        raise RuntimeError(f"Configured LLM secret alias is absent: {secret_name}")

    candidates = [name.strip() for name in str(llm["model"]).split(",") if name.strip()]
    last_error = None
    started = time.perf_counter()
    for candidate_index, candidate in enumerate(candidates):
        observer = MessageObserver()
        model = OpenAIModel(
            observer=observer,
            model_id=candidate,
            api_key=api_key,
            api_base=llm["base_url"],
            model_factory=llm.get("provider"),
            display_name="runtime-memory-verification",
            temperature=0,
            max_output_tokens=64,
            timeout_seconds=120,
        )
        try:
            response = model([
                {"role": "system", "content": "Return only the requested verification marker."},
                {"role": "user", "content": "Return exactly: RUNTIME_MEMORY_REAL_MODEL_OK"},
            ])
            break
        except Exception as exc:  # noqa: BLE001 - try the next configured model
            last_error = exc
    else:
        raise RuntimeError(f"All {len(candidates)} configured LLM candidates failed") from last_error
    elapsed = time.perf_counter() - started
    content = str(getattr(response, "content", response) or "")
    return {
        "marker_present": "RUNTIME_MEMORY_REAL_MODEL_OK" in content,
        "response_chars": len(content),
        "elapsed_seconds": elapsed,
        "retry_count": getattr(model, "last_retry_count", None),
        "diagnostics_present": getattr(model, "last_response_diagnostics", None) is not None,
        "model_alias": str(llm.get("id", "llm")),
        "candidate_index": candidate_index,
    }


def main() -> None:
    print(json.dumps(run_probe(), sort_keys=True))


if __name__ == "__main__":
    main()
