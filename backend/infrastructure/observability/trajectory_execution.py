# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SDK lifecycle callback that allocates one ID before local span capture."""

import logging
from contextlib import contextmanager
from dataclasses import replace
from uuid import uuid4

from .trajectory_io import TrajectoryConflict, TrajectoryCorrupt
from .trajectory_store import CaptureIdentity

logger = logging.getLogger(__name__)


def execution_observer(*, capturing, store=None):
    @contextmanager
    def observe(metadata):
        if (
            metadata.conversation_id is None
            or not metadata.user_id
            or not metadata.tenant_id
        ):
            yield metadata
            return
        from management.db.trajectory.repository import ExecutionRepository

        repository = ExecutionRepository()
        identity = CaptureIdentity(
            str(metadata.tenant_id),
            str(metadata.user_id),
            str(metadata.conversation_id),
            str(metadata.agent_id) if metadata.agent_id is not None else None,
        )
        trajectory_id = str(uuid4())
        # Registration uses the same PG authority as the run, including when capture is disabled.
        prior_turn = 0
        if store is not None:
            try:
                prior_turn = store.manifest(identity)["next_turn_no"] - 1
            except FileNotFoundError:
                pass
            except (OSError, TrajectoryConflict, TrajectoryCorrupt):
                # PG remains authoritative when an archive cannot be inspected.
                logger.warning("trajectory.prior_turn_unavailable")
        turn = repository.begin(
            identity,
            trajectory_id,
            agent_version_no=metadata.agent_version_no,
            capturing=capturing,
            **({"prior_turn": prior_turn} if store is not None else {}),
        )
        bound = replace(
            metadata,
            extra_metadata={
                **(metadata.extra_metadata or {}),
                "trajectory_id": trajectory_id,
                "trajectory_turn_no": turn,
            },
        )
        try:
            yield bound
        finally:
            # Durable archive compensation publishes captured metrics; no duplicate run is allocated here.
            logger.debug("trajectory.execution_registered")

    return observe
