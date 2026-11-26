# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Return terminal state only for this fixture's tenant-owned idle conversation."""

import json
import sys
from uuid import UUID, uuid5

from sqlalchemy import select

from infrastructure.rdb.agent_execution import AgentExecution
from infrastructure.rdb.client import get_db_session


token, identifier = sys.argv[1:]
tenant = str(uuid5(UUID(token), "owner:tenant"))
user = str(uuid5(UUID(token), "owner:user"))
with get_db_session() as session:
    executions = session.scalars(select(AgentExecution).where(
        AgentExecution.tenant_id == tenant, AgentExecution.created_by == user,
        AgentExecution.conversation_id == int(identifier), AgentExecution.delete_flag == "N",
    )).all()
    rows = [{"run_id": row.run_id, "status": row.status, "assistant_message_id": row.assistant_message_id}
            for row in executions]
print("SCALING_IDLE " + json.dumps(rows))
