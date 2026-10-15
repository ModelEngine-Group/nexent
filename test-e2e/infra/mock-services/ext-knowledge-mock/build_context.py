# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Pack the batch-owned Docker build context for the ext-knowledge mock.

The repository root cannot serve as the build context: the root .dockerignore
excludes test/, and the AIDP mock embedded in the image must come from the
CURRENT checkout (never from a stale snapshot). This helper copies the mock
source, its seeds, the Dockerfile and the AIDP mock directory (source plus
graph JSON) from one worktree into a limited, explicitly enumerated context
directory, and records a manifest with the checkout HEAD and per-file hashes
so the deployment step can pass a stable ``build_manifest_sha256`` identity
into the container.

Usage:
    python build_context.py --output <context-dir> [--repo <repo-root>]

The output directory is created (or replaced) with exactly:
    mock/            server.py, control.py, *_mock.py, seeds/*.json
    aidp_mock_servers/   aidp_mgmt_mock_server.py, graph_config_template_chinese.json
    Dockerfile
    build-manifest.json  (NOT copied into the image; the Dockerfile only
                          copies the two subdirectories)

Failures (missing source file, unreadable checkout, AIDP JSON absent) abort
before anything is packed, so a stale or partial context can never silently
back a build.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

SCHEMA_VERSION = 1

MOCK_FILES = (
    "server.py",
    "control.py",
    "mock_common.py",
    "datamate_mock.py",
    "dify_mock.py",
    "ragflow_mock.py",
    "idata_mock.py",
    "haotian_mock.py",
    "assets_mock.py",
    "fault_provider_mock.py",
    "requirements.txt",
)
MOCK_SEED_FILES = (
    "assets.json",
    "datamate.json",
    "dify.json",
    "haotian.json",
    "idata.json",
    "ragflow.json",
)
AIDP_FILES = (
    "aidp_mgmt_mock_server.py",
    "graph_config_template_chinese.json",
)
# Never packed, whatever their name: runtime state, caches, credentials.
EXCLUDED_NAMES = {"_state", "__pycache__", ".env", "credentials"}


def _repo_root(configured: str | None) -> Path:
    if configured:
        root = Path(configured).resolve()
    else:
        root = Path(__file__).resolve().parents[4]
    if not (root / "test-e2e/infra/mock-services/ext-knowledge-mock").is_dir():
        raise ValueError(f"{root} does not look like the Nexent checkout")
    return root


def _git_head(repo: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"could not read the checkout HEAD: {exc}") from exc


def _entry(path: str, sha256: str, size: int) -> dict:
    return {"path": path, "sha256": sha256, "bytes": size}


def pack(repo: Path, output: Path) -> dict:
    mock_dir = repo / "test-e2e/infra/mock-services/ext-knowledge-mock"
    aidp_dir = repo / "test/ext_components/aidp/mock_servers"

    # Enumerate the full file set up front so a missing file aborts before
    # any copying happens (no half-packed contexts).
    sources: list[tuple[Path, str]] = []
    for name in MOCK_FILES:
        sources.append((mock_dir / name, f"mock/{name}"))
    for name in MOCK_SEED_FILES:
        sources.append((mock_dir / "seeds" / name, f"mock/seeds/{name}"))
    sources.append((mock_dir / "Dockerfile", "Dockerfile"))
    for name in AIDP_FILES:
        sources.append((aidp_dir / name, f"aidp_mock_servers/{name}"))

    missing = [str(source) for source, _ in sources if not source.is_file()]
    if missing:
        raise ValueError("required source files are missing: " + ", ".join(missing))

    if output.exists():
        # A context directory is batch-owned; replace it wholesale rather
        # than merging with a previous pack.
        shutil.rmtree(output)
    output.mkdir(parents=True)

    files = []
    for source, relative in sources:
        data = source.read_bytes()
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        files.append(_entry(relative, hashlib.sha256(data).hexdigest(), len(data)))

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "head": _git_head(repo),
        "sources": {
            "mock": "test-e2e/infra/mock-services/ext-knowledge-mock",
            "aidp": "test/ext_components/aidp/mock_servers",
        },
        "excluded": sorted(EXCLUDED_NAMES),
        "files": files,
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    (output / "build-manifest.json").write_bytes(manifest_bytes)
    manifest["build_manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="Context directory to create (replaced if present)")
    parser.add_argument("--repo", type=str, default=None, help="Repository root (default: this checkout)")
    args = parser.parse_args(argv)
    try:
        manifest = pack(_repo_root(args.repo), args.output.resolve())
    except (ValueError, OSError) as exc:
        print(f"Packing failed: {exc}", file=sys.stderr)
        return 1
    # Print the values the deployment step must export so the container
    # reports a verifiable identity through GET /_mock/identity.
    print(f"context: {args.output.resolve()}")
    print(f"EXT_KNOWLEDGE_SOURCE_REVISION={manifest['head']}")
    print(f"EXT_KNOWLEDGE_BUILD_MANIFEST_SHA256={manifest['build_manifest_sha256']}")
    print(f"files: {len(manifest['files'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
