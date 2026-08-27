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
      if (usedHeight > containerHeight) {
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

interface ConversationVirtualSpacerInput {
  totalCount: number;
  pendingDeletionCount: number;
  loadedContentHeight: number;
  rowHeight: number;
  groupHeaderHeight: number;
  groupCount: number;
  contentPadding: number;
}

export const calculateConversationVirtualSpacerHeight = (
  input: ConversationVirtualSpacerInput
): number => {
  const remainingTotal = Math.max(
    0,
    Math.floor(input.totalCount) - Math.floor(input.pendingDeletionCount)
  );
  const estimatedTotalHeight =
    remainingTotal * Math.max(0, input.rowHeight) +
    Math.max(0, Math.floor(input.groupCount)) *
      Math.max(0, input.groupHeaderHeight) +
    Math.max(0, input.contentPadding);

  return Math.max(
    0,
    estimatedTotalHeight -
      Math.max(0, input.contentPadding) -
      Math.max(0, input.loadedContentHeight)
  );
};

interface ConversationLoadedBoundaryInput {
  scrollTop: number;
  clientHeight: number;
  loadedBoundary: number;
  threshold?: number;
}

export const isConversationLoadedBoundaryReached = (
  input: ConversationLoadedBoundaryInput
): boolean =>
  input.scrollTop + input.clientHeight >=
  input.loadedBoundary - Math.max(0, input.threshold ?? 0);

export class ConversationViewportCoordinator {
  private nextPageSize: number | null = null;
  private pendingOffsetAdjustment = 0;
  private metadata: ConversationListMetadata | null = null;
  private listeners = new Set<() => void>();

  requestNextPageSize(pageSize: number): void {
    this.nextPageSize = this.normalizePageSize(pageSize);
  }

  takeNextPageSize = (fallback: number): number => {
    const pageSize = this.nextPageSize ?? this.normalizePageSize(fallback);
    this.nextPageSize = null;
    return pageSize;
  };

  clearNextPageSize(): void {
    this.nextPageSize = null;
  }

  recordDeletedLoadedItem(): void {
    this.pendingOffsetAdjustment += 1;
  }

  getOffsetAdjustment = (): number => this.pendingOffsetAdjustment;

  commitOffsetAdjustment = (count: number): void => {
    this.pendingOffsetAdjustment = Math.max(
      0,
      this.pendingOffsetAdjustment - Math.max(0, Math.floor(count))
    );
  };

  resetPagination = (): void => {
    this.nextPageSize = null;
    this.pendingOffsetAdjustment = 0;
    if (this.metadata !== null) {
      this.metadata = null;
      this.notify();
    }
  };

  setMetadata = (metadata: ConversationListMetadata): void => {
    this.metadata = metadata;
    this.notify();
  };

  getSnapshot = (): ConversationListMetadata | null => this.metadata;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private notify(): void {
    this.listeners.forEach((listener) => listener());
  }

  private normalizePageSize(pageSize: number): number {
    return Math.min(100, Math.max(1, Math.ceil(pageSize)));
  }
}

export const newChatConversationViewport =
  new ConversationViewportCoordinator();
