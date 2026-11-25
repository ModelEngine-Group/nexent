-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

CREATE INDEX IF NOT EXISTS idx_agent_execution_conversation_history
    ON nexent.agent_execution_t (conversation_id, agent_scope, create_time DESC, run_id DESC)
    WHERE delete_flag = 'N';
