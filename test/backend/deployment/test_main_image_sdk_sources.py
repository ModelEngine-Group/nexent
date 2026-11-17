# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""The production SDK installation must consume implementation files, not just metadata."""

from pathlib import Path


def test_main_builder_copies_sdk_implementation_before_installation():
    root = Path(__file__).resolve().parents[3]
    source = (root / "deploy/images/dockerfiles/main/Dockerfile").read_text(encoding="utf-8")
    builder = source.split(" AS builder", 1)[1].split("FROM base AS final", 1)[0]
    installation = builder.index('"/opt/sdk[performance]"')
    copies = [line.split() for line in builder[:installation].splitlines() if line.startswith("COPY ")]
    assert any(parts[1].rstrip("/") == "sdk" and parts[2].rstrip("/") == "/opt/sdk" for parts in copies), (
        "The main image must copy the SDK implementation before building its installed package"
    )
