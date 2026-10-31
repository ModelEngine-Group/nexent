# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Kubernetes deployment entry point; account import is shared with migrate_docker.py."""

import hashlib
import json
import sys

try:
    from . import migrate_docker as migrate
except ImportError:
    import migrate_docker as migrate


def source_target(args, values):
    host = values.get("SUPABASE_POSTGRES_HOST")
    if host and host not in {"supabase_db", "supabase-db-mini", "nexent-supabase-db"} and not args.source_container:
        return {"remote": True}
    selected = args.source_container or "nexent-supabase-db"
    prefix = ["kubectl", "--namespace", args.namespace]
    output = migrate._command([*prefix, "get", "deployment", selected, "--ignore-not-found", "-o", "json"])
    if not output:
        return None
    deployment = json.loads(output)
    if deployment["spec"].get("replicas", 1) == 0:
        migrate._command([*prefix, "scale", "deployment/" + selected, "--replicas=1"])
    migrate._command([*prefix, "rollout", "status", "deployment/" + selected, "--timeout=" + str(args.wait_timeout) + "s"])
    return {"target": selected, "deployment": deployment}


def preserve_storage(args, source, path):
    """Resolve actual pod volumes, including custom/existing PVC names."""
    volumes = source["deployment"]["spec"]["template"]["spec"].get("volumes", [])
    claims = sorted({volume["persistentVolumeClaim"]["claimName"] for volume in volumes if "persistentVolumeClaim" in volume})
    if not claims:
        raise migrate.MigrationSetupError("Source database has no persistent claim; verify its storage before upgrading")
    backup = {"deployment": source["deployment"], "storage": []}
    for name in claims:
        claim = json.loads(migrate._command(["kubectl", "--namespace", args.namespace, "get", "pvc", name, "-o", "json"]))
        volume_name = claim.get("spec", {}).get("volumeName")
        if not volume_name:
            raise migrate.MigrationSetupError("Source PVC is not bound; preserving the old release")
        volume = json.loads(migrate._command(["kubectl", "get", "pv", volume_name, "-o", "json"]))
        backup["storage"].append({"claim": claim, "volume": volume})
    # Save the original definitions before changing any reclaim policy.
    migrate._private_json(path.with_name(path.stem + "-storage.json"), backup)
    for item in backup["storage"]:
        volume = item["volume"]
        if volume["spec"].get("persistentVolumeReclaimPolicy") != "Retain":
            migrate._command(["kubectl", "patch", "pv", volume["metadata"]["name"], "--type=merge", "-p",
                              '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'])


def upgrade(args):
    # Bind retries to the selected API server; contexts can change between runs.
    cluster = migrate._command(["kubectl", "config", "view", "--minify", "-o", "json"])
    servers = [item["cluster"]["server"] for item in json.loads(cluster).get("clusters", [])]
    if len(servers) != 1:
        raise migrate.MigrationSetupError("Select exactly one Kubernetes cluster context before migration")
    args.cluster_identity = hashlib.sha256(servers[0].encode()).hexdigest()
    return migrate.automatic_upgrade(args, source_resolver=source_target, storage_preserver=preserve_storage)


def main():
    if not any(arg == "--deploy-phase" or arg.startswith("--deploy-phase=") for arg in sys.argv):
        raise SystemExit("Use --deploy-phase prepare or --deploy-phase apply --apply; legacy up/down is Docker-only")
    sys.argv.extend(["--deployment", "kubernetes"])
    return migrate.main(upgrade=upgrade)


if __name__ == "__main__":
    raise SystemExit(main())
