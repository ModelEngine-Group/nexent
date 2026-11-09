-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.conversation_message_t
    ADD COLUMN IF NOT EXISTS question_bookmarked BOOLEAN NOT NULL DEFAULT FALSE;
COMMENT ON COLUMN nexent.conversation_message_t.question_bookmarked IS
    'Owner question bookmark; independent of message content and conversation activity';
