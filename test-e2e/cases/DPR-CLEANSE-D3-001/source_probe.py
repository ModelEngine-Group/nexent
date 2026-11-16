# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real MinIO/PostgreSQL publication and lost-reply reconciliation through storage ports."""

import asyncio
import hashlib
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from contracts.constants import environment
from contracts.knowledge_cleanse import KnowledgeCleanseRequest
from ledger_probe import check_ledger_access
from management.services.file.cleanse_authorization import KnowledgeCleanseAuthorization
from management.services.file.source_publish import SourcePublisher
from management.services.file.source_recovery import reconcile_sources
from management.services.file.source_upload import upload_knowledge_source
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.storage.errors import OutcomeUnknown
from nexent.storage.models import ObjectRef, RecordQuery, StorageScope

from infrastructure.object_storage.port import ObjectBinding, S3ObjectStore
from infrastructure.rdb.cleanse_resources import TABLES, bind_cleanse_resources
from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.knowledge_storage_record import KnowledgeStorageObject
from infrastructure.rdb.source_binding import DATASET, bind_source_records
from infrastructure.rdb.tenant_config_record import TenantConfig
from infrastructure.rdb.upload_records import LEDGER, QUOTA, bind_upload_records


def check_source_publication(engine, port, context):
    def client_factory(remaining):
        return boto3.client(
            "s3",
            endpoint_url=f"http://127.0.0.1:{port}",
            aws_access_key_id="fixture-user",
            aws_secret_access_key="fixture-password",
            region_name="us-east-1",
            config=Config(
                connect_timeout=min(1, remaining),
                read_timeout=min(5, remaining),
                retries={"total_max_attempts": 1},
                proxies={"http": None, "https": None},
            ),
        )

    deadline = time.monotonic() + 30
    while True:
        try:
            with closing(client_factory(1)) as client:
                client.list_buckets()
            break
        except (BotoCoreError, ClientError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)
    with closing(client_factory(5)) as client:
        client.create_bucket(Bucket="source-proof")
    table = KnowledgeFileLifecycle.__table__
    KnowledgeStorageObject.__table__.create(engine, checkfirst=True)
    TenantConfig.__table__.create(engine, checkfirst=True)
    with engine.begin() as conn:
        for file_id, key in (
            ("c" * 32, "source.txt"),
            ("d" * 32, "lost.txt"),
            ("f" * 32, "recover.txt"),
            ("9" * 32, "quota.txt"),
        ):
            conn.execute(
                table.insert().values(
                    file_id=file_id,
                    tenant_id="tenant-a",
                    knowledge_id=1,
                    index_name="kb-one",
                    original_filename=key,
                    bucket_name="source-proof",
                    object_name=key,
                    status="UPLOADING",
                    stage="UPLOAD",
                    version=0,
                    delete_flag="N",
                    created_by="user-a",
                    updated_by="user-a",
                    upload_owner_service="nexent-config",
                )
            )
    records = bind_source_records(
        StorageScope("management", "tenant-a", "user-a", {DATASET}), engine
    )
    objects = S3ObjectStore(
        StorageScope("management", "tenant-a", "user-a", {"files"}),
        ObjectBinding(
            "files",
            "source-proof",
            "",
            {"management"},
            writable=True,
            exact_keys=frozenset(
                {"source.txt", "lost.txt", "recover.txt", "quota.txt"}
            ),
        ),
        client_factory,
    )
    resource_records = bind_cleanse_resources(
        StorageScope("management", "tenant-a", "user-a", set(TABLES)), engine
    )
    try:
        publisher = SourcePublisher(records, objects)
        data = b"Real published knowledge source."
        source = publisher.publish(
            "c" * 32,
            data,
            content_type="text/plain",
            expected_version=0,
            context=context(),
        )
        assert source.sha256 == hashlib.sha256(data).hexdigest()
        with objects.open_read(
            ObjectRef(source.space, source.key), context=context()
        ) as stream:
            assert stream.read() == data
        with engine.begin() as conn:
            conn.execute(
                table.update()
                .where(table.c.file_id == "c" * 32)
                .values(status="UPLOADED", stage="UPLOAD", version=3)
            )
        authorization = KnowledgeCleanseAuthorization(
            resource_records, user_id="user-a"
        )
        request = KnowledgeCleanseRequest(
            knowledge_id=1,
            file_id="c" * 32,
            file_version=0,
            source=source,
            filename="source.txt",
            idempotency_key="published",
        )
        assert authorization.authorize(request, context=context()) == source

        class LostReply:
            scope = objects.scope
            writes = 0

            def put(self, *args, **kwargs):
                self.writes += 1
                objects.put(*args, **kwargs)
                raise OutcomeUnknown()

            def stat(self, *args, **kwargs):
                return objects.stat(*args, **kwargs)

        lost = LostReply()
        uncertain = SourcePublisher(records, lost)
        try:
            uncertain.publish(
                "d" * 32,
                data,
                content_type="text/plain",
                expected_version=0,
                context=context(),
            )
        except OutcomeUnknown:
            pass
        else:
            raise AssertionError("lost upload acknowledgement was treated as confirmed")
        recovered = uncertain.publish(
            "d" * 32,
            data,
            content_type="text/plain",
            expected_version=0,
            context=context(),
        )
        assert recovered.sha256 == source.sha256 and lost.writes == 1
        assert (
            records.get(DATASET, "d" * 32, context=context())["source_revision"]
            == recovered.version
        )
        with engine.begin() as conn:
            conn.execute(
                table.insert().values(
                    file_id="e" * 32,
                    tenant_id="tenant-a",
                    knowledge_id=1,
                    index_name="kb-one",
                    original_filename="managed.txt",
                    bucket_name="source-proof",
                    object_name="managed.txt",
                    status="UPLOADING",
                    stage="UPLOAD",
                    version=0,
                    delete_flag="N",
                    created_by="user-a",
                    updated_by="user-a",
                )
            )
        record = records.get(DATASET, "e" * 32, context=context())
        settings = {
            "POSTGRES_HOST": engine.url.host,
            "POSTGRES_PORT": str(engine.url.port),
            "POSTGRES_USER": engine.url.username,
            "NEXENT_POSTGRES_PASSWORD": engine.url.password,
            "POSTGRES_DB": engine.url.database,
            "MINIO_ENDPOINT": f"http://127.0.0.1:{port}",
            "MINIO_ACCESS_KEY": "fixture-user",
            "MINIO_SECRET_KEY": "fixture-password",
            "MINIO_DEFAULT_BUCKET": "source-proof",
            "MINIO_REGION": "us-east-1",
        }
        previous = {key: getattr(environment, key) for key in settings}

        async def managed():
            manager = ThreadManager(
                service_name="source-proof",
                lane_policies={
                    "file-upload": LanePolicy(
                        name="file-upload",
                        max_workers=1,
                        max_queue_size=0,
                        queue_timeout_seconds=0,
                        cancel_grace_seconds=2,
                        shutdown_grace_seconds=5,
                    )
                },
            )
            manager.start()
            try:
                confirmed = await upload_knowledge_source(
                    record, data, "text/plain", manager=manager, timeout=15
                )
                assert confirmed.sha256 == source.sha256
                assert (
                    record["stage"] == "SOURCE_ACCOUNTED"
                    and record["storage_object_id"]
                )
                charged_id = record["storage_object_id"]
                replay = await upload_knowledge_source(
                    record, data, "text/plain", manager=manager, timeout=15
                )
                assert replay == confirmed and record["storage_object_id"] == charged_id
            finally:
                drained = await manager.shutdown(timeout=5)
                assert not drained.stuck_execution_ids
                assert manager.snapshot().active_count == 0

        try:
            for key, value in settings.items():
                setattr(environment, key, value)
            asyncio.run(managed())
            # A separate lost reply is recovered by the production discovery root.
            try:
                uncertain.publish(
                    "f" * 32,
                    data,
                    content_type="text/plain",
                    expected_version=0,
                    context=context(),
                )
            except OutcomeUnknown:
                pass
            else:
                raise AssertionError("lost reply did not preserve an uncertain intent")
            with engine.begin() as conn:
                conn.execute(
                    table.update()
                    .where(table.c.file_id == "f" * 32)
                    .values(
                        source_upload_started_at=datetime.now(timezone.utc)
                        - timedelta(minutes=10),
                    )
                )
            assert reconcile_sources("nexent-config", context=context()) == {
                "uploaded": 1
            }
            row = records.get(DATASET, "f" * 32, context=context())
            assert row["status"] == "UPLOADED" and row["stage"] == "UPLOAD"
            assert row["storage_object_id"] is not None
            assert row["updated_by"] == "source-reconciliation"
            assert (
                row["source_revision"] is not None
                and row["source_sha256"] == source.sha256
            )
            assert lost.writes == 2
            with engine.begin() as conn:
                conn.execute(
                    TenantConfig.__table__.insert().values(
                        tenant_id="tenant-a",
                        config_key="KB_QUOTA_TENANT_HARD_LIMIT_BYTES",
                        config_value=str(len(data) * 2),
                        delete_flag="N",
                    )
                )
            try:
                uncertain.publish(
                    "9" * 32,
                    data,
                    content_type="text/plain",
                    expected_version=0,
                    context=context(),
                )
            except OutcomeUnknown:
                pass
            else:
                raise AssertionError(
                    "quota fixture did not retain the lost-reply intent"
                )
            with engine.begin() as conn:
                conn.execute(
                    table.update()
                    .where(table.c.file_id == "9" * 32)
                    .values(
                        source_upload_started_at=datetime.now(timezone.utc)
                        - timedelta(minutes=10),
                    )
                )
            assert reconcile_sources("nexent-config", context=context()) == {
                "quota_review": 1
            }
            blocked = records.get(DATASET, "9" * 32, context=context())
            assert (
                blocked["status"] == "UPLOADING" and blocked["stage"] == "SOURCE_REVIEW"
            )
            assert blocked["error_code"] == "STORAGE_QUOTA_EXCEEDED"
            accounting = bind_upload_records(
                StorageScope(
                    "management", "tenant-a", "proof", {DATASET, LEDGER, QUOTA}
                ),
                engine,
                with_policy=True,
            )
            try:
                assert (
                    accounting.sum(
                        LEDGER, "raw_bytes", RecordQuery(), context=context()
                    )
                    == len(data) * 3
                )
                assert (
                    accounting.get(
                        LEDGER, blocked["storage_object_id"], context=context()
                    )["status"]
                    == "COMMITTED"
                )
            finally:
                accounting.close()
            assert objects.stat(
                ObjectRef("files", "quota.txt"), context=context()
            ).size == len(data)
            assert lost.writes == 3
            check_ledger_access(engine, objects, blocked, len(data), context)
        finally:
            for key, value in previous.items():
                setattr(environment, key, value)
        assert (
            records.get(DATASET, "e" * 32, context=context())["source_revision"]
            is not None
        )
    finally:
        resource_records.close()
        objects.close()
        records.close()
