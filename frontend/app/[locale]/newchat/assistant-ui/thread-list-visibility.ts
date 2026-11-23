type ConversationEntry = {
  id: string;
  hasRemoteId: boolean;
  isRunning: boolean;
};

export function getVisibleAgentThreads<T extends ConversationEntry>(
  entries: readonly T[],
  expanded: boolean,
  activeThreadId?: string,
  generatedTitles?: ReadonlyMap<string, string>
): readonly T[] {
  if (expanded) return entries;
  return entries.filter(
    (entry) =>
      entry.id === activeThreadId &&
      (entry.hasRemoteId || entry.isRunning || generatedTitles?.has(entry.id))
  );
}
