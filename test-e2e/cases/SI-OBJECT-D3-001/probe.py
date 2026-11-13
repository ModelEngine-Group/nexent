# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute real Management object conversion in a disposable image container."""

import asyncio
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from contracts.constants import environment
from management import thread_management
from management.services.file import office_preview
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import ByteRange, ObjectRef, OperationContext

from infrastructure.file_processing import conversion, process
from infrastructure.object_storage import port
from infrastructure.object_storage.composition import bind_preview_objects


def context():
    return OperationContext("object-probe", time.monotonic() + 30)


def document():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:p><w:r><w:t>StorageInterface isolated Office conversion probe.</w:t></w:r></w:p></w:body>
</w:document>""",
        )
    return output.getvalue()


def main():
    # Reproduce a launcher that forks a long-lived child, as soffice does.
    with tempfile.TemporaryDirectory() as work:
        marker = Path(work) / "child.pid"
        command = [
            sys.executable,
            "-c",
            (
                "import os,time,pathlib; pid=os.fork(); "
                f"pathlib.Path({str(marker)!r}).write_text(str(pid)) if pid else None; time.sleep(60)"
            ),
        ]
        started = time.monotonic()
        try:
            process.run_conversion_process(command, timeout=1)
        except subprocess.TimeoutExpired:
            pass
        else:
            raise AssertionError("process-tree deadline was ignored")
        assert time.monotonic() - started < 7
        child_pid = int(marker.read_text())
        child_stat = Path(f"/proc/{child_pid}/stat")
        assert not child_stat.exists() or child_stat.read_text().split()[2] == "Z"

    # Infrastructure maintenance setup and test-only observations use a private client.
    admin = boto3.client(
        "s3",
        endpoint_url=environment.MINIO_ENDPOINT,
        aws_access_key_id=environment.MINIO_ACCESS_KEY,
        aws_secret_access_key=environment.MINIO_SECRET_KEY,
        config=Config(
            connect_timeout=1, read_timeout=1, retries={"total_max_attempts": 1}
        ),
    )
    deadline = time.monotonic() + 30
    while True:
        try:
            admin.create_bucket(Bucket=environment.MINIO_DEFAULT_BUCKET)
            break
        except (BotoCoreError, ClientError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)
    source, target = "docs/source.docx", "preview/final.pdf"
    store = bind_preview_objects(frozenset({source, target}))
    raw = document()
    uploaded = store.put(
        ObjectRef("files", source),
        io.BytesIO(raw),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size=len(raw),
        context=context(),
    )
    with store.open_read(
        uploaded.ref, byte_range=ByteRange(0, 4), context=context()
    ) as stream:
        assert stream.read() == raw[:4]
    try:
        store.stat(ObjectRef("files", "docs/ungranted.docx"), context=context())
    except ScopeDenied:
        pass
    else:
        raise AssertionError("ungranted key was accessible")

    async def convert():
        manager = thread_management.config_thread_manager
        manager.start()
        try:
            result = await office_preview.convert_preview(
                source, target, manager=manager, timeout=90
            )
        finally:
            shutdown = await manager.shutdown(timeout=35)
        return result, shutdown

    result, shutdown = asyncio.run(convert())
    assert not shutdown.stuck_execution_ids
    assert result.size > 100
    with store.open_read(
        result.ref, byte_range=ByteRange(0, 5), context=context()
    ) as stream:
        assert stream.read() == b"%PDF-"
    keys = sorted(
        item["Key"]
        for item in admin.list_objects_v2(Bucket=environment.MINIO_DEFAULT_BUCKET)[
            "Contents"
        ]
    )
    assert keys == sorted([source, target]), keys
    hashes = {}
    for module in (port, office_preview, thread_management, conversion, process):
        path = Path(module.__file__)
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    admin.close()
    store.close()
    print(
        json.dumps(
            {
                "pdf_bytes": result.size,
                "keys": keys,
                "stuck": [],
                "source_hashes": hashes,
            }
        )
    )


if __name__ == "__main__":
    main()
