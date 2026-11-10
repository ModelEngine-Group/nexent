# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Finish stream projections left behind by the previous Runtime process."""

import logging

from infrastructure.rdb.conversation_state import fail_streaming_assistant_messages
from infrastructure.redis.run_state import runtime_state_service

logger = logging.getLogger(__name__)


def recover_streaming_runs() -> int:
    messages = fail_streaming_assistant_messages()
    for message in messages:
        if user_id := message["user_id"]:
            conversation_id = int(message["conversation_id"])
            runtime_state_service.mark_run_finished(user_id, conversation_id, "failed")
            runtime_state_service.mark_stream_completed(user_id, conversation_id, "failed")
    logger.info("Recovered %d interrupted assistant streams", len(messages))
    return len(messages)
