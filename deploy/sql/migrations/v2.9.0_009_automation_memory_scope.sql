-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.agent_automation_run_t
    ADD COLUMN IF NOT EXISTS projection_memory_agent_id INTEGER CHECK (projection_memory_agent_id > 0);

COMMENT ON COLUMN nexent.agent_automation_run_t.projection_memory_agent_id IS
    'Authorized Agent used for Memory completion by the pending AgentOS projection.';

ALTER TABLE nexent.conversation_memory_completion_t
    ADD COLUMN IF NOT EXISTS source_message_id INTEGER CHECK (source_message_id > 0);

COMMENT ON COLUMN nexent.conversation_memory_completion_t.source_message_id IS
    'Original automation prompt message ID, required for automation jobs. Chat jobs locate their paired prompt by index.';
