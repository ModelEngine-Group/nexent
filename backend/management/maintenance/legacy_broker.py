# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Record legacy broker and file counts after publishers and workers have stopped."""

import argparse
import json
import logging
import os
from pathlib import Path
from time import monotonic
from uuid import uuid4

from contracts.knowledge_maintenance import BROKER_INVENTORY, LEGACY_INGESTION_INVENTORY
from contracts.roles import has_any_role
from management.services.knowledge_base.quota_authorization import quota_identity_roles
from nexent.storage.errors import ScopeDenied, Unavailable
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.legacy_tasks import legacy_broker_ports

logger = logging.getLogger(__name__)


def _read(actor, context):
    with legacy_broker_ports(actor, context=context) as (identity, broker, files):
        if not has_any_role(quota_identity_roles(identity, actor, context=context), {"SU"}):
            raise ScopeDenied()
        broker_counts = broker.get(BROKER_INVENTORY, "queues", context=context)
        inflight = files.get(LEGACY_INGESTION_INVENTORY, "files", context=context)
        if inflight is None:
            raise Unavailable(operation_id=context.operation_id)
        if not has_any_role(quota_identity_roles(identity, actor, context=context), {"SU"}):
            raise ScopeDenied()
        broker_counts.pop("id")
        return {**broker_counts, "legacy_inflight_files": inflight["count"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--user-id", required=True, help="Actual operator with active SU membership")
    parser.add_argument("--legacy-quiesced", required=True, action="store_true",
                        help="Operator confirms legacy publishers and early-ack workers have stopped")
    parser.add_argument("--output", required=True, type=Path, help="New private JSON receipt")
    parser.add_argument("--timeout", type=int, default=30, help="Total deadline in seconds, at most 300")
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 300 or any(
        not value.strip() or len(value) > 100 for value in (args.tenant_id, args.user_id)
    ):
        parser.error("Select an actual operator and tenant and a timeout in 1..300 seconds")
    context = OperationContext("legacy-broker-" + uuid4().hex, monotonic() + args.timeout)
    try:
        actor = ServicePrincipal(args.user_id, args.tenant_id)
        evidence = _read(actor, context)
        broker_empty = not (
            any(evidence["queues"].values()) or evidence["shared_default_queue"]
            or evidence["shared_unacked"] or evidence["shared_unacked_index"]
        )
        result = {
            "operation_id": context.operation_id, "actor_id": actor.user_id, "tenant_id": actor.tenant_id,
            "legacy_quiesced_attested": True, **evidence, "broker_empty": broker_empty,
            "migration_ready": False,
        }
        context.remaining()
        with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=True)
            output.write("\n")
        return 0 if broker_empty and evidence["legacy_inflight_files"] == 0 else 3
    except KeyboardInterrupt:
        return 130
    except Exception as error:  # noqa: BLE001 -- Driver details and Redis URLs are private.
        logger.error("legacy_broker_inspection_failed operation_id=%s exception_type=%s",
                     context.operation_id, type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
