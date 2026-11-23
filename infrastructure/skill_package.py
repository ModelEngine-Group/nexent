# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Content-addressed snapshots of authorized Skill files in platform object storage."""

import io
import re
from contextlib import closing
from hashlib import sha256
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from infrastructure.object_storage.client import minio_client
from infrastructure.skill_execution import MAX_SKILL_BYTES, MAX_SKILL_FILES, skill_path_segment


MAX_ARCHIVE_BYTES = MAX_SKILL_BYTES + 2 * 1024 * 1024


def released_skill_files(tenant, agent, version, row):
    """Recheck the exact approved package and binding even when the shared directory changes."""
    from infrastructure.skill_execution import skill_execution_revision
    package = row["release_package"]
    files = load_skill_package(tenant, package["skill_id"], package["digest"])
    if skill_execution_revision(tenant, agent, version, row, files) != package["revision"]:
        raise ValueError("Published Skill configuration differs from its verified revision")
    return files


def _validate_paths(files):
    if "SKILL.md" not in files or len(files) > MAX_SKILL_FILES:
        raise ValueError("Invalid Skill package manifest")
    folded = set()
    for name in files:
        if len(name.encode("utf-8")) > 1024 or name.casefold() in folded:
            raise ValueError("Ambiguous or oversized Skill path")
        for part in name.split("/"):
            skill_path_segment(part)
        folded.add(name.casefold())
    for name in folded:
        parts = name.split("/")
        if any("/".join(parts[:i]) in folded for i in range(1, len(parts))):
            raise ValueError("Skill package contains a file as a directory")


def encode_skill_package(files: dict[str, bytes]) -> bytes:
    _validate_paths(files)
    if sum(map(len, files.values())) > MAX_SKILL_BYTES:
        raise ValueError("Oversized Skill package")
    buf = io.BytesIO()
    with ZipFile(buf, "w") as archive:
        for name in sorted(files):
            info = ZipInfo(name)
            info.create_system = 3
            info.external_attr = 0o600 << 16
            archive.writestr(info, files[name])
    return buf.getvalue()


def _object_key(tenant_id, skill_id, digest):
    if not tenant_id or skill_id <= 0 or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid Skill package reference")
    owner = sha256(tenant_id.encode()).hexdigest()
    return f"evolution/skill-packages/{owner}/{skill_id}/{digest}.zip"


def store_skill_package(tenant_id, skill_id, files):
    payload = encode_skill_package(files)
    digest = sha256(payload).hexdigest()
    ok, _ = minio_client.upload_fileobj(io.BytesIO(payload), _object_key(tenant_id, skill_id, digest))
    if not ok:
        raise OSError("Could not store Skill package")
    return digest


def load_skill_package(tenant_id, skill_id, digest):
    ok, stream = minio_client.get_file_stream(_object_key(tenant_id, skill_id, digest))
    if not ok:
        raise OSError("Could not read Skill package")
    with closing(stream):
        payload = stream.read(MAX_ARCHIVE_BYTES + 1)
    if len(payload) > MAX_ARCHIVE_BYTES or sha256(payload).hexdigest() != digest:
        raise ValueError("Skill package digest mismatch")
    with ZipFile(io.BytesIO(payload)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        _validate_paths(names)
        if (any(entry.compress_type != ZIP_STORED for entry in entries)
                or sum(entry.file_size for entry in entries) > MAX_SKILL_BYTES):
            raise ValueError("Invalid Skill package contents")
        return {entry.filename: archive.read(entry) for entry in entries}
