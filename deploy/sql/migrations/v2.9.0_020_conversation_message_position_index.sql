-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Find the latest active message at a conversation position without scanning message history.
CREATE INDEX IF NOT EXISTS idx_conversation_message_position
    ON nexent.conversation_message_t (conversation_id, message_index, message_id DESC)
    WHERE delete_flag = 'N';
