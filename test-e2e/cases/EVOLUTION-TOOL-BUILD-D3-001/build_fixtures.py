# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Build only self-authored pilot images on the local Docker host."""

import json
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "nexent/nexent-management:latest"


def build_images(client):
    parent = client.images.get(BASE)
    result = {}
    with tempfile.TemporaryDirectory() as folder:
        context = Path(folder)

        def build(recipe):
            (context / "Dockerfile").write_text(f"FROM {BASE}\n" + recipe, encoding="utf8")
            image, _ = client.images.build(
                path=str(context), rm=True, forcerm=True, pull=False, network_mode="none"
            )
            layers = parent.attrs["RootFS"]["Layers"]
            assert image.attrs["RootFS"]["Layers"][: len(layers)] == layers
            return image.id

        shutil.copy(Path(__file__).with_name("fixture.py"), context)
        for name, expression in {
            "base": 'reference.lower() if reference.startswith("Q") else reference',
            "corrected": "reference",
            "regressed": 'reference.lower() if reference.startswith("R") else reference',
        }.items():
            (context / "fixture_entry.py").write_text(
                f"def entry(reference):\n    return {expression}\n", encoding="utf8"
            )
            result[name] = build(
                "COPY fixture*.py /opt/\nUSER 65534:65534\nENTRYPOINT "
                + json.dumps(["python", "/opt/fixture.py"])
                + "\nCMD []\n"
            )

        for rel in ("backend/contracts", "sdk/nexent/core/agents/resources"):
            shutil.copytree(ROOT / rel, context / rel, ignore=shutil.ignore_patterns("__pycache__"))
        for rel in (
            "management/cli/tool_repair_check.py",
            "management/cli/tool_build_probe.py",
            "management/services/evaluation/tool_use.py",
        ):
            dst = context / "backend" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / "backend" / rel, dst)
        result["verifier"] = build(
            "COPY backend/ /opt/backend/\nCOPY sdk/ /opt/backend/.venv/lib/python3.11/site-packages/\n"
        )
    return result


if __name__ == "__main__":
    import docker

    print(json.dumps(build_images(docker.from_env())))
