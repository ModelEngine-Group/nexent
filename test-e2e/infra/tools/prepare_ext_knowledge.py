# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Explicit operator deployment of the optional external shared knowledge mock.

`up --execute` builds from this checkout and publishes local attach metadata.
`ensure --execute` reuses that external image and configuration without writes.
Do not add it to the default suite D0: suite-owned processes use the same port.
Changed mock sources require explicit operator up outside an active batch.
Neither command changes product containers, credentials or existing hooks.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import yaml

from ext_attach import (
    AttachError, CONFIG_NAME, EXT_LOGICAL_SERVICES, _FileLock, _read_state,
    _request, config_problems, endpoint_lock_paths, load_config, repo_root,
    validate_config,
)


def packer(repo: Path):
    source = repo / "test-e2e/infra/mock-services/ext-knowledge-mock/build_context.py"
    spec = importlib.util.spec_from_file_location("ext_context_packer", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_matches(repo: Path, context: Path) -> bool:
    """Compare source bytes, not unrelated product commits or runtime state."""
    manifest = json.loads((context / "build-manifest.json").read_text(encoding="utf-8"))
    roots = {"mock": repo / manifest["sources"]["mock"],
             "aidp_mock_servers": repo / manifest["sources"]["aidp"]}
    for row in manifest["files"]:
        relative = Path(row["path"])
        source = (repo / manifest["sources"]["mock"] / "Dockerfile" if row["path"] == "Dockerfile"
                  else roots[relative.parts[0]].joinpath(*relative.parts[1:]))
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != row["sha256"]:
            return False
        packed = context / relative
        if not packed.is_file() or hashlib.sha256(packed.read_bytes()).hexdigest() != row["sha256"]:
            return False
    return True


def deployment_env(context: Path, config: dict) -> dict:
    return dict(os.environ, EXT_KNOWLEDGE_BUILD_CONTEXT=str(context),
                EXT_KNOWLEDGE_MOCK_RUN_ID=config["owner_run_id"],
                EXT_KNOWLEDGE_SOURCE_REVISION=config["source_revision"],
                EXT_KNOWLEDGE_BUILD_MANIFEST_SHA256=config["build_manifest_sha256"])


def deploy(repo: Path, context: Path, config: dict, *, build: bool) -> None:
    command = [sys.executable, str(repo / "test-e2e/infra/mock-services/deploy.py"), "up", "ext-knowledge",
               "--project", config["compose_project"], "--product-network", config["product_network"],
               "--timeout", "180"]
    if not build:
        command.append("--no-build")
    subprocess.run(command, cwd=repo, env=deployment_env(context, config), check=True, timeout=900)


def product_probes(config: dict) -> None:
    """Verify actual product-side DNS/network without changing product env."""
    result = subprocess.run(["docker", "network", "inspect", config["product_network"]],
                            capture_output=True, text=True, check=True, timeout=15)
    members = json.loads(result.stdout)[0].get("Containers", {})
    names = {item.get("Name") for item in members.values()}
    targets = [name for name in ("nexent-config", "nexent-runtime", "nexent-data-process") if name in names]
    if not targets:
        raise AttachError("No product service is present on the configured product network")
    probe = ("import json,urllib.request; "
             "o=urllib.request.build_opener(urllib.request.ProxyHandler({})); "
             "r=o.open(" + repr(config["product_url"] + "/health") + ",timeout=10); "
             "d=json.load(r); assert d['status']=='ok' and all(v=='ok' for v in d['services'].values())")
    for name in targets:
        subprocess.run(["docker", "exec", name, "python", "-c", probe],
                       check=True, capture_output=True, timeout=20)


def atomic_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".next")
    temporary.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    if os.name != "nt":
        temporary.chmod(0o600)
    temporary.replace(path)


def prepare(repo: Path, home: Path, action: str, network: str) -> dict:
    runtime = home / "runtime/ext-knowledge"
    state_path = runtime / "deployment.json"
    config_path = home / "config" / CONFIG_NAME
    existing = load_config(home, repo) if config_path.exists() else None
    if action == "ensure" and not existing:
        raise AttachError("Run prepare_ext_knowledge.py up --execute before enabling the D0 ensure hook")
    config = existing or {
        "schema_version": 1, "runner_url": "http://127.0.0.1:30090",
        "product_url": "http://ext-knowledge:30090", "owner_run_id": "pending",
        "source_revision": "pending", "build_manifest_sha256": "0" * 64,
        "compose_project": "nexent-mock-ext-knowledge", "product_network": network,
        "lock_directory": str(home.parent / ".nexent-test-locks"),
        "logical_services": list(EXT_LOGICAL_SERVICES),
    }
    validate_config(config, home)
    lock_path, state_file = endpoint_lock_paths(config)
    lock = _FileLock(lock_path)
    lock.acquire()
    try:
        state = _read_state(state_file)
        if state and not state.get("released"):
            raise AttachError("Previous attach was not released; verify ownership and recover before deployment")
        # The check also applies to ensure: never replace a foreign listener
        # just because an old local deployment receipt happens to exist.
        try:
            _, identity = _request(config["runner_url"] + "/_mock/identity")
        except AttachError as exc:
            if "URLError" not in str(exc) and "ConnectionRefusedError" not in str(exc):
                raise
        else:
            if not existing or any(str(identity.get(k, "")) != str(existing[c]) for k, c in (
                    ("run_id", "owner_run_id"), ("source_revision", "source_revision"),
                    ("build_manifest_sha256", "build_manifest_sha256"))):
                raise AttachError("Refusing to replace an unowned or foreign knowledge mock")
        if action == "ensure":
            if not state_path.is_file():
                raise AttachError("Deployment receipt is missing; run explicit operator up first")
            receipt = json.loads(state_path.read_text(encoding="utf-8"))
            context = Path(receipt["context"])
            if not context.resolve().is_relative_to(runtime.resolve()):
                raise AttachError("Deployment context is outside the owned runtime directory")
            if not source_matches(repo, context):
                raise AttachError("Mock source/context changed; run explicit operator up outside an active batch")
            manifest_hash = hashlib.sha256((context / "build-manifest.json").read_bytes()).hexdigest()
            if manifest_hash != config["build_manifest_sha256"]:
                raise AttachError("Packed context does not match the configured deployment identity")
        else:
            deployment_id = "ext-" + uuid.uuid4().hex
            context = runtime / deployment_id / "context"
            manifest = packer(repo).pack(repo, context)
            config = {**config, "owner_run_id": deployment_id,
                      "source_revision": manifest["head"],
                      "build_manifest_sha256": manifest["build_manifest_sha256"]}
        deploy(repo, context, config, build=action == "up")
        _, identity = _request(config["runner_url"] + "/_mock/identity")
        if any(str(identity.get(k, "")) != str(config[c]) for k, c in (
                ("run_id", "owner_run_id"), ("source_revision", "source_revision"),
                ("build_manifest_sha256", "build_manifest_sha256"))):
            raise AttachError("Deployment identity mismatch; local attach configuration was not published")
        product_probes(config)
        if action == "up":
            atomic_yaml(config_path, config)
        problems = config_problems(home, repo, EXT_LOGICAL_SERVICES, live=True)
        if problems:
            raise AttachError("; ".join(problems))
        receipt = {"context": str(context), "owner_run_id": config["owner_run_id"],
                   "source_revision": config["source_revision"],
                   "build_manifest_sha256": config["build_manifest_sha256"],
                   "product_network": config["product_network"], "status": "READY"}
        if action == "up":
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        return receipt
    finally:
        lock.release()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("up", "ensure"))
    parser.add_argument("--test-home", type=Path, required=True)
    parser.add_argument("--repo")
    parser.add_argument("--product-network", default="nexent_network")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        print("Preview only: add --execute to deploy the owned mock; no product containers are changed")
        return 0
    try:
        receipt = prepare(repo_root(args.repo), args.test_home.resolve(), args.action, args.product_network)
        print(json.dumps(receipt, indent=2))
        return 0
    except (AttachError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"External knowledge preparation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
