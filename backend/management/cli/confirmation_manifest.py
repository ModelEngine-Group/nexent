# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Build the fingerprint manifest in an independent evaluator's private workspace."""

import argparse
import json
from getpass import getpass
from hashlib import sha256
from pathlib import Path, PureWindowsPath

from pydantic import ValidationError
import httpx

from contracts.confirmation import ConfirmationManifest, PrivateTask
from contracts.evolution_sources import example_source_keys, task_digest


def compile_private_suite(path):
    path = Path(path).resolve(strict=True)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Private suite exceeds the manifest size limit")
    raw = json.loads(path.read_bytes())
    if not isinstance(raw, list) or not 1 <= len(raw) <= 500:
        raise ValueError("Supply between one and 500 private tasks")
    cases, scope = [], None
    for entry in raw:
        task = PrivateTask.model_validate(entry)
        if scope and scope != (task.agent_id, task.version_no):
            raise ValueError("Use one published Agent version per suite")
        scope = task.agent_id, task.version_no
        files = []
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
            files.append({"name":attachment.name, "size":size, "sha256":digest.hexdigest()})
        frozen = task.model_dump(mode="json", exclude_none=True, exclude={"attachments", "conversation_digest"})
        frozen["attachments"] = files
        if task.conversation_digest:
            frozen["trace_source"] = {"source_group":task.conversation_digest}
        cases.append({"digest":task_digest(frozen), "sources":sorted(example_source_keys(frozen))})
    return ConfirmationManifest(format="nexent-confirmation-v1", agent_id=scope[0], version_no=scope[1], cases=cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("private_suite", type=Path)
    parser.add_argument("--register-at", metavar="URL", help="Management API base URL including /api")
    args = parser.parse_args()
    try:
        manifest = compile_private_suite(args.private_suite)
    except ValidationError as exc:
        parser.exit(2, f"Invalid private suite ({exc.error_count()} validation errors).\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Invalid private suite: {type(exc).__name__}.\n")
    if args.register_at:
        token = getpass("Independent evaluator session token: ")
        try:
            response = httpx.post(args.register_at.rstrip("/") + "/agent-evolution/confirmation-suites",
                                  json=manifest.canonical(), headers={"Authorization":f"Bearer {token}"}, timeout=60)
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
