export const getVisibleThreadIds = (
  threadIds: readonly string[],
  threadItems: ReadonlyArray<{ id: string; remoteId?: string }>,
  serverConversationIds?: ReadonlyMap<string, string>
): string[] => {
  const remoteIds = new Map(
    threadItems.map((item) => [item.id, item.remoteId])
  );
  return threadIds.filter((id) => {
    const conversationId = Number(
      serverConversationIds?.get(id) || remoteIds.get(id)
    );
    return Number.isInteger(conversationId) && conversationId > 0;
  });
};
