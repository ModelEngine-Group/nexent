# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Build the fingerprint manifest in an independent evaluator's private workspace."""

import argparse
import json
from collections import Counter
from getpass import getpass
from hashlib import sha256
from pathlib import Path, PureWindowsPath

from pydantic import ValidationError
import httpx

from contracts.confirmation import ConfirmationLockRequest, ConfirmationManifest, ConfirmationPolicy, PrivateTask
from contracts.evolution_sources import example_source_keys, task_digest


def read_private_suite(path):
    path = Path(path).resolve(strict=True)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Private suite exceeds the manifest size limit")
    raw = json.loads(path.read_bytes())
    if not isinstance(raw, list) or not 1 <= len(raw) <= 500:
        raise ValueError("Supply between one and 500 private tasks")
    cases, families, tasks, scope = [], Counter(), {}, None
    for entry in raw:
        task = PrivateTask.model_validate(entry)
        if scope and scope != (task.agent_id, task.version_no):
            raise ValueError("Use one published Agent version per suite")
        scope = task.agent_id, task.version_no
        families[task.family] += 1
        files = []
        paths = {}
        remaining = 64 * 1024 * 1024
        for attachment in task.attachments:
            relative = PureWindowsPath(attachment.object_name)
            if relative.anchor or ".." in relative.parts:
                raise ValueError("Use a relative path inside the private workspace")
            file = (path.parent / attachment.object_name).resolve(strict=True)
            if not file.is_relative_to(path.parent) or not file.is_file():
                raise ValueError("Attachment falls outside the private workspace")
            size = 0
            digest = sha256()
            with file.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > remaining:
                        raise ValueError("Private task attachments exceed the 64 MiB limit")
                    digest.update(chunk)
            remaining -= size
            paths[attachment.name] = file
            files.append({"name":attachment.name, "size":size, "sha256":digest.hexdigest()})
        frozen = task.model_dump(mode="json", exclude_none=True, exclude={"attachments", "conversation_digest"})
        frozen["attachments"] = files
        if task.conversation_digest:
            frozen["trace_source"] = {"source_group":task.conversation_digest}
        digest = task_digest(frozen)
        tasks[digest] = (frozen, paths)
        cases.append({"digest":digest, "sources":sorted(example_source_keys(frozen))})
    manifest = ConfirmationManifest(format="nexent-confirmation-v1", agent_id=scope[0], version_no=scope[1], cases=cases)
    return manifest, families, tasks


def inspect_private_suite(path):
    manifest, families, _ = read_private_suite(path)
    return manifest, families


def compile_private_suite(path):
    manifest, _ = inspect_private_suite(path)
    return manifest


def check_private_coverage(policy, families):
    if (policy.minimum_valid_pairs > sum(families.values()) or
            any(families.get(name, 0) < required for name, required in policy.family_minimums.items())):
        raise ValueError("The private tasks do not cover the declared scope")


def verify_private_protocol(manifest, families, protocol):
    recipe = protocol["recipe"]
    check_private_coverage(ConfirmationPolicy.model_validate(protocol["policy"]), families)
    expected = task_digest([recipe["tenant_id"],protocol["suite_id"],protocol["suite_digest"],
                            protocol["experiment_id"],protocol["candidate_digest"],protocol["policy"]])
    if (protocol["digest"] != expected or protocol["suite_digest"] != task_digest(manifest.canonical())
            or task_digest(recipe) != protocol["candidate_digest"] or recipe["experiment_id"] != protocol["experiment_id"]
            or (manifest.agent_id,manifest.version_no) != (recipe["agent_id"],recipe["version_no"])):
        raise ValueError("Local materials do not match the locked comparison")
    return {"lock_id":protocol["lock_id"],"digest":expected,"verified_tasks":len(manifest.cases)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("private_suite", type=Path)
    parser.add_argument("--register-at", "--api", metavar="URL", help="Management API base URL including /api")
    parser.add_argument("--experiment", type=int, help="Eligible experiment submitted by an Agent editor")
    parser.add_argument("--candidate-digest", help="Digest returned when the editor submitted the candidate")
    parser.add_argument("--policy", type=Path, help="Private evaluator's preregistered thresholds (JSON)")
    parser.add_argument("--verify-lock", type=int, help="Check the local private suite against an existing confirmation lock")
    args = parser.parse_args()
    try:
        manifest, families = inspect_private_suite(args.private_suite)
        comparison = None
        if args.verify_lock is not None and (not args.register_at or args.verify_lock < 1
                or any(x is not None for x in (args.experiment,args.candidate_digest,args.policy))):
            parser.error("Use --verify-lock with --api and without a new comparison")
        if any(x is not None for x in (args.experiment,args.candidate_digest,args.policy)):
            if not all((args.register_at,args.experiment,args.candidate_digest,args.policy)):
                parser.error("Use --register-at, --experiment, --candidate-digest and --policy together for a comparison")
            policy = ConfirmationPolicy.model_validate_json(args.policy.read_bytes())
            check_private_coverage(policy, families)
            comparison = ConfirmationLockRequest(experiment_id=args.experiment,candidate_digest=args.candidate_digest,
                                                 suite_digest=task_digest(manifest.canonical()),policy=policy)
    except ValidationError as exc:
        parser.exit(2, f"Invalid private suite ({exc.error_count()} validation errors).\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Invalid private suite: {type(exc).__name__}.\n")
    if args.register_at:
        token = getpass("Independent evaluator session token: ")
        try:
            root = args.register_at.rstrip("/") + "/agent-evolution/confirmation-suites"
            with httpx.Client(headers={"Authorization":f"Bearer {token}"},timeout=60) as client:
                if args.verify_lock is not None:
                    response = client.get(args.register_at.rstrip("/") + f"/agent-evolution/confirmation-locks/{args.verify_lock}")
                    response.raise_for_status()
                    try:
                        preflight = verify_private_protocol(manifest,families,response.json()["data"])
                    except (KeyError,ValueError) as exc:
                        parser.exit(2, f"Private suite or protocol mismatch ({type(exc).__name__}).\n")
                    print(json.dumps(preflight,sort_keys=True))
                    return
                response = client.post(root,json=manifest.canonical())
                response.raise_for_status()
                suite = response.json()["data"]
                if comparison:
                    if suite["digest"] != comparison.suite_digest:
                        parser.exit(2, "Registered suite differs from the local materials.\n")
                    response = client.post(f"{root}/{suite['suite_id']}/locks",json=comparison.model_dump())
                    response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            parser.exit(2, f"Registration rejected (HTTP {exc.response.status_code}).\n")
        except httpx.RequestError:
            parser.exit(2, "Could not reach Management.\n")
        print(json.dumps(response.json()["data"], sort_keys=True))
    else:
        print(json.dumps(manifest.canonical(), sort_keys=True))


if __name__ == "__main__":
    main()
