// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

type UserBoundary = {
  retry_user_message_id: number;
  retry_message_index?: number;
};
type RetryMessage = {
  id: string;
  role: string;
  metadata?: { custom?: Record<string, unknown> };
};

// Store only acknowledged server identities, never question text or credentials.
const savedUsers = new Map<string, UserBoundary>();

export function acknowledgeConversationUser(
  localId: string,
  id: number,
  index: number
) {
  if (
    !Number.isSafeInteger(id) ||
    id <= 0 ||
    !Number.isSafeInteger(index) ||
    index < 0
  )
    return;
  savedUsers.delete(localId);
  savedUsers.set(localId, {
    retry_user_message_id: id,
    retry_message_index: index,
  });
  if (savedUsers.size > 1000)
    savedUsers.delete(savedUsers.keys().next().value!);
}

export function getConversationRetryTarget(
  messages: readonly RetryMessage[],
  parentId: string | null
): UserBoundary | null {
  const user = messages.find(
    (item) => item.id === parentId && item.role === "user"
  );
  if (!user) return null;
  const live = savedUsers.get(user.id);
  if (live) return live;
  if (
    !/^\d+$/.test(user.id) ||
    !Number.isSafeInteger(Number(user.id)) ||
    Number(user.id) <= 0
  )
    return null;
  const index = user.metadata?.custom?.historicalMessageIndex;
  return {
    retry_user_message_id: Number(user.id),
    ...(typeof index === "number" && Number.isInteger(index) && index >= 0
      ? { retry_message_index: index }
      : {}),
  };
}
