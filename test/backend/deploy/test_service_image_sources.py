# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Independent service targets retain executable tool plugins without peer sources."""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("service,peer", [("management", "runtime"), ("runtime", "management")])
def test_independent_target_installs_deployment_plugins_without_peer_sources(service, peer):
    dockerfile = (ROOT / "deploy/images/dockerfiles/main/Dockerfile").read_text(encoding="utf-8")
    section = dockerfile.split("FROM backend-common AS " + service + "\n", 1)[1].split("\nFROM ", 1)[0]
    copies = [line.split() for line in section.splitlines() if line.startswith("COPY ")]
    assert any(parts[1:] == ["backend/tool_collection/langchain", "/opt/backend/tool_collection/langchain"]
               for parts in copies)
    assert any(parts[1] == "backend/" + service for parts in copies)
    assert all(parts[1] not in {"backend", "backend/" + peer} for parts in copies)
    assert (ROOT / "backend/tool_collection/langchain").is_dir()
