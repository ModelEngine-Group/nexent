-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
CREATE INDEX IF NOT EXISTS idx_agent_execution_terminal_window
    ON nexent.agent_execution_t (tenant_id, conversation_id, created_by, create_time)
    WHERE delete_flag='N' AND status IN ('completed','failed','stopped');
CREATE INDEX IF NOT EXISTS idx_admission_business_execution
    ON nexent.conversation_run_admission_t (tenant_id, run_id)
    WHERE delete_flag='N' AND prepared_assistant_id IS NOT NULL;
