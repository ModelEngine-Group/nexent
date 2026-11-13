# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Backfill and verify PG projections before enabling the new list implementation.

Run ``python -m scripts.backfill_trajectory_summaries`` from backend with its
configured environment after applying the migration and stopping old processes.
"""

import logging

from contracts.constants import environment as config
from infrastructure.observability.trajectory_runtime import authorize_capture
from infrastructure.observability.trajectory_store import TrajectoryFileStore
from management.db.client import get_db_session
from management.db.trajectory.models import TrajectoryExecution
from management.db.trajectory.repository import ExecutionRepository
from management.services.trajectory.projection import Projector, manifest_runs

logger = logging.getLogger(__name__)


def backfill(store, repository):
    projector = Projector(store, repository)
    while repository.placeholders() == 1000:
        pass
    count = 0
    for identity in store.identities():
        # A missing current owner is an orphan, never a resource to republish.
        try:
            authorize_capture(identity)
        except PermissionError:
            continue
        projector.sync(identity)
        manifest = store.manifest(identity)
        with get_db_session() as session:
            for run in manifest_runs(manifest):
                row = session.get(TrajectoryExecution, run["trajectory_id"])
                if (
                    row is None
                    or row.delete_flag != "N"
                    or row.conversation_id != int(identity.conversation_id)
                    or row.created_by != identity.owner_user_id
                    or row.turn_no != run["turn_no"]
                    or (
                        projector.archive.available(run) == "expired"
                        and row.status != "expired"
                    )
                ):
                    raise RuntimeError("Trajectory projection verification failed")
        count += 1
    return count


def main():
    repository = ExecutionRepository()
    store = TrajectoryFileStore(
        config.TRAJECTORY_ROOT_DIR,
        authorize=authorize_capture,
        initialization_guard=repository.initialize,
        expire_callback=repository.expire,
        retention_days=config.TRAJECTORY_RETENTION_DAYS,
        storage_mode=config.TRAJECTORY_STORAGE_MODE,
    )
    count = backfill(store, repository)
    logger.info("trajectory.backfill_verified conversations=%s", count)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
