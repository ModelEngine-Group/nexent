# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read the complete declared source inventory before semantic normalization."""

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping

from pydantic import Field, HttpUrl, ValidationError, model_validator

from nexent.core.model_service.profiles.contracts import AtomicProfileReference, NonBlankString, ProfileContract


SourceKind = Literal["model", "provider", "provider_model"]


class SourceEntry(ProfileContract):
    """One source file whose bytes are pinned by the catalog manifest."""

    kind: SourceKind
    path: NonBlankString
    content_sha256: NonBlankString
    origin: Literal["models_dev", "nexent"] = "models_dev"
    source_revision: NonBlankString | None = None
    source_url: HttpUrl | None = None

    @model_validator(mode="after")
    def validate_origin(self):
        if self.origin == "nexent":
            if self.source_revision is None or self.source_url is None:
                raise ValueError("Local sources require a revision and documentation URL")
        elif self.source_revision is not None or self.source_url is not None:
            raise ValueError("Upstream sources use the pinned upstream provenance")
        return self


class SourceManifest(ProfileContract):
    """Versioned source inventory; mapping and runtime API bindings are separate."""

    schema_version: int = Field(ge=1, le=1)
    source_schema_ref: Literal["models_dev_authored_v1"]
    upstream_url: Literal["https://github.com/anomalyco/models.dev"]
    upstream_revision: NonBlankString
    sources: list[SourceEntry] = Field(min_length=1)


class SourceReadError(ValueError):
    """Sanitized source diagnostic without embedding file contents or OS errors."""

    def __init__(self, category: str, file_path: str, source_kind: str = "manifest"):
        self.category = category
        self.file_path = file_path
        self.source_kind = source_kind
        self.source_path = ""
        self.rule_id = "source_inventory_v1"
        super().__init__(f"{category}: {source_kind}: {file_path}")


@dataclass(frozen=True)
class SourceDocument:
    """Deeply read-only authored document, not a resolved runtime profile."""

    kind: SourceKind
    key: str
    file_path: str
    content_sha256: str
    data: Mapping[str, object]
    origin: str = "models_dev"
    source_revision: str | None = None
    source_url: str | None = None


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _read(root: Path, path: str, kind: str) -> bytes:
    try:
        candidate = (root / path).resolve()
        if not candidate.is_relative_to(root):
            raise SourceReadError("SOURCE_PATH_OUTSIDE_ROOT", path, kind)
        return candidate.read_bytes()
    except (OSError, RuntimeError):
        raise SourceReadError("SOURCE_FILE_UNAVAILABLE", path, kind) from None


def _parse(data: bytes, path: str, kind: str) -> dict:
    try:
        return tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise SourceReadError("SOURCE_TOML_INVALID", path, kind) from None


def _key(entry: SourceEntry) -> str:
    parts = entry.path.split("/")
    if entry.kind == "model" and len(parts) >= 3 and parts[0] == "models":
        return entry.path[len("models/") : -len(".toml")]
    if entry.kind == "provider" and len(parts) == 3 and parts[0] == "providers" and parts[2] == "provider.toml":
        return parts[1]
    if entry.kind == "provider_model" and len(parts) >= 4 and parts[0] == "providers" and parts[2] == "models":
        return parts[1] + "/" + "/".join(parts[3:])[: -len(".toml")]
    raise SourceReadError("SOURCE_KIND_PATH_MISMATCH", entry.path, entry.kind)


@dataclass(frozen=True)
class SourceInventory:
    """Metadata from the same manifest bytes used to validate source documents."""

    upstream_revision: str
    source_schema_ref: str
    manifest_sha256: str
    documents: tuple[SourceDocument, ...]


def read_inventory(root: Path) -> SourceInventory:
    """Fail the whole inventory on errors; do not expose a partial catalog."""
    root = root.resolve()
    manifest_bytes = _read(root, "manifest.toml", "manifest")
    raw_manifest = _parse(manifest_bytes, "manifest.toml", "manifest")
    try:
        manifest = SourceManifest.model_validate(raw_manifest)
        if len(manifest.upstream_revision) != 40 or any(
            char not in "0123456789abcdef" for char in manifest.upstream_revision
        ):
            raise ValueError("Invalid upstream commit")
    except (ValidationError, ValueError):
        raise SourceReadError("SOURCE_MANIFEST_INVALID", "manifest.toml") from None

    documents = []
    identities = set()
    paths = set()
    for entry in manifest.sources:
        try:
            AtomicProfileReference(
                key=entry.path,
                catalog_revision=manifest.upstream_revision,
                file_path=entry.path,
                content_sha256=entry.content_sha256,
            )
        except ValidationError:
            raise SourceReadError("SOURCE_REFERENCE_INVALID", entry.path, entry.kind) from None
        if not entry.path.endswith(".toml") or entry.path.split("/")[-1] == ".toml":
            raise SourceReadError("SOURCE_KIND_PATH_MISMATCH", entry.path, entry.kind)
        key = _key(entry)
        identity = (entry.kind, key)
        if entry.path in paths or identity in identities:
            raise SourceReadError("SOURCE_DUPLICATE", entry.path, entry.kind)
        paths.add(entry.path)
        identities.add(identity)
        data = _read(root, entry.path, entry.kind)
        if hashlib.sha256(data).hexdigest() != entry.content_sha256:
            raise SourceReadError("SOURCE_DIGEST_MISMATCH", entry.path, entry.kind)
        parsed = _parse(data, entry.path, entry.kind)
        documents.append(SourceDocument(entry.kind, key, entry.path, entry.content_sha256, _freeze(parsed),
            entry.origin, entry.source_revision, str(entry.source_url) if entry.source_url is not None else None))
    return SourceInventory(
        manifest.upstream_revision,
        manifest.source_schema_ref,
        hashlib.sha256(manifest_bytes).hexdigest(),
        tuple(documents),
    )


def read_sources(root: Path) -> tuple[SourceDocument, ...]:
    """Return complete authored documents without changing the existing interface."""
    return read_inventory(root).documents
