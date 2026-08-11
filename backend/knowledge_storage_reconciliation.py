"""Command-line entry point for KB source-object backfill and reconciliation."""

import argparse
import json
from typing import Optional, Sequence

from consts.const import VectorDatabaseType
from services.knowledge_storage_reconciliation_service import (
    KnowledgeStorageReconciliationService,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the maintenance command parser."""
    parser = argparse.ArgumentParser(
        description="Backfill or reconcile the knowledge-base MinIO source ledger."
    )
    parser.add_argument("operation", choices=("backfill", "reconcile"))
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--updated-by", default="storage-reconciliation-cli")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist evidence-backed repairs. The default is a non-mutating dry run.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run one maintenance operation and print its structured report."""
    from services.vectordatabase_service import get_vector_db_core

    args = build_parser().parse_args(argv)
    vdb_core = get_vector_db_core(VectorDatabaseType.ELASTICSEARCH)
    service = KnowledgeStorageReconciliationService(
        tenant_id=args.tenant_id,
        vdb_core=vdb_core,
        updated_by=args.updated_by,
    )
    report = (
        service.backfill(apply=args.apply)
        if args.operation == "backfill"
        else service.reconcile(apply=args.apply)
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 1 if report["summary"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
