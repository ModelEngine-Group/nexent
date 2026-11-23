# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import io

import pytest


def test_package_roundtrip_is_order_independent_and_tenant_scoped(monkeypatch):
    from infrastructure import skill_package as packages

    objects = {}

    def upload(stream, key):
        objects[key] = stream.read()
        return True, ""

    def read(key):
        return (True, io.BytesIO(objects[key])) if key in objects else (False, None)

    monkeypatch.setattr(packages.minio_client, "upload_fileobj", upload)
    monkeypatch.setattr(packages.minio_client, "get_file_stream", read)
    files = {"scripts/convert.py": b"pass", "SKILL.md": b"guide", "assets/logo": b"\x00\xff"}
    digest = packages.store_skill_package("A", 7, files)
    assert packages.store_skill_package("A", 7, dict(reversed(files.items()))) == digest
    assert packages.load_skill_package("A", 7, digest) == files
    with pytest.raises(OSError):
        packages.load_skill_package("B", 7, digest)
    with pytest.raises(OSError):
        packages.load_skill_package("A", 8, digest)
    objects[next(iter(objects))] = b"corrupt"
    with pytest.raises(ValueError, match="digest"):
        packages.load_skill_package("A", 7, digest)


@pytest.mark.parametrize("name", ["../x", "scripts/../x", "/x", "C:/x", "scripts//x", "skill.MD", "SKILL.md/x"])
def test_package_rejects_nonportable_paths(name):
    from infrastructure.skill_package import encode_skill_package

    with pytest.raises(ValueError):
        encode_skill_package({"SKILL.md": b"guide", name: b"data"})
