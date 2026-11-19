# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Select complete creator checkpoints before falling back to durable units."""

from redis.exceptions import RedisError

from management.services.agent.replay import subscribe_shared_checkpoint


async def creator_checkpoint_stream(service, channel, generation, user_id, conversation_id):
    """A source is usable only when it belongs to the generation being resumed."""
    if channel is not None and (
        not generation or getattr(channel, "generation", None) == generation
    ):
        return channel.subscribe_with_history(0, include_replay_checkpoint=True)
    if service.enabled:
        try:
            checkpoint = await service.read_replay_checkpoint_async(user_id, conversation_id)
        except (RedisError, RuntimeError):
            return None
        if checkpoint and checkpoint.get("generation") == generation and checkpoint.get("entries"):
            return subscribe_shared_checkpoint(service, user_id, conversation_id, checkpoint)
    return None
