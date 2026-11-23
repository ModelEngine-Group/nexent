type RetryMessage = {
  id: string;
  role: string;
  metadata?: { custom?: Record<string, unknown> };
};

export function getCreationRetryTarget(
  messages: readonly RetryMessage[],
  parentId: string | null
): { retry_user_message_id?: number; retry_message_index: number } | null {
  const userPosition = messages.findIndex(
    (item) => item.id === parentId && item.role === "user"
  );
  if (userPosition < 0) return null;

  const user = messages[userPosition];
  const savedIndex = user.metadata?.custom?.historicalMessageIndex;
  const retry_message_index =
    typeof savedIndex === "number" && Number.isInteger(savedIndex)
      ? savedIndex
      : messages.slice(0, userPosition).filter((item) => item.role === "user")
          .length * 2;
  const retry_user_message_id = /^\d+$/.test(user.id)
    ? Number(user.id)
    : undefined;

  return { retry_message_index, ...(retry_user_message_id ? { retry_user_message_id } : {}) };
}
