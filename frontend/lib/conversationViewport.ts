export const DEFAULT_CONVERSATION_PAGE_SIZE = 20;

export interface ConversationListMetadata {
  total: number;
  today: number;
  last_7_days: number;
  older: number;
}

// Before metadata arrives, one group header requires the most rows to fill the
// viewport. Extra real group headers only consume more height, so this avoids
// leaving the initial page short without a separate metadata request.
const UNKNOWN_CONVERSATION_GROUP_COUNTS = [100, 0, 0] as const;

export const getConversationViewportGroupCounts = (
  metadata?: ConversationListMetadata | null
): readonly number[] =>
  metadata
    ? [metadata.today, metadata.last_7_days, metadata.older]
    : UNKNOWN_CONVERSATION_GROUP_COUNTS;

interface ConversationViewportInput {
  containerHeight: number;
  rowHeight: number;
  groupHeaderHeight: number;
  groupGap?: number;
  contentPadding?: number;
  groupCounts: readonly number[];
}

export const calculateConversationViewport = (
  input: ConversationViewportInput
): { initialLimit: number; totalHeight: number } => {
  const { containerHeight, rowHeight, groupHeaderHeight } = input;
  const groupGap = Math.max(0, input.groupGap ?? 0);
  const contentPadding = Math.max(0, input.contentPadding ?? 0);
  const counts = input.groupCounts.map((count) => Math.max(0, count));
  const nonEmptyGroups = counts.filter((count) => count > 0).length;
  const total = counts.reduce((sum, count) => sum + count, 0);
  const totalHeight =
    total * Math.max(0, rowHeight) +
    nonEmptyGroups * Math.max(0, groupHeaderHeight) +
    Math.max(0, nonEmptyGroups - 1) * groupGap +
    contentPadding;

  if (containerHeight <= 0 || rowHeight <= 0 || groupHeaderHeight < 0) {
    return {
      initialLimit: Math.min(
        total || DEFAULT_CONVERSATION_PAGE_SIZE,
        DEFAULT_CONVERSATION_PAGE_SIZE
      ),
      totalHeight,
    };
  }

  let usedHeight = contentPadding;
  let rows = 0;
  let renderedGroups = 0;
  for (const count of counts) {
    if (count <= 0) continue;
    if (renderedGroups > 0) usedHeight += groupGap;
    usedHeight += groupHeaderHeight;
    renderedGroups += 1;
    for (let index = 0; index < count; index += 1) {
      usedHeight += rowHeight;
      rows += 1;
      if (usedHeight >= containerHeight) {
        return { initialLimit: Math.min(100, rows), totalHeight };
      }
    }
  }

  return { initialLimit: Math.min(100, rows), totalHeight };
};

export const getConversationDateBoundaries = (): {
  todayStartMs: number;
  weekStartMs: number;
} => {
  const now = new Date();
  const todayStartMs = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate()
  ).getTime();
  return { todayStartMs, weekStartMs: todayStartMs - 7 * 86_400_000 };
};

export class ConversationViewportCoordinator {
  private metadata: ConversationListMetadata | null = null;
  private initialLimit: number | null = null;
  private listeners = new Set<() => void>();

  private notify(): void {
    this.listeners.forEach((listener) => listener());
  }

  setMetadata(metadata: ConversationListMetadata): void {
    this.metadata = metadata;
    this.initialLimit = null;
    this.notify();
  }

  reset(): void {
    this.metadata = null;
    this.initialLimit = null;
    this.notify();
  }

  getMetadata(): ConversationListMetadata | null {
    return this.metadata;
  }

  getSnapshot = (): ConversationListMetadata | null => this.metadata;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  resolveInitialLimit(limit: number): void {
    this.initialLimit = Math.max(1, Math.ceil(limit));
  }

  takePageLimit(): number {
    const limit = this.initialLimit ?? DEFAULT_CONVERSATION_PAGE_SIZE;
    this.initialLimit = null;
    return limit;
  }
}

export const newChatConversationViewport =
  new ConversationViewportCoordinator();
