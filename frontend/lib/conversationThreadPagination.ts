export interface ConversationPage<
  TItem,
  TMetadata extends { total: number } = { total: number },
> {
  items: TItem[];
  metadata: TMetadata;
}

interface ConversationThreadPageLoaderOptions<
  TItem,
  TThread,
  TMetadata extends { total: number },
> {
  pageSize: number;
  takeNextPageSize: (fallback: number) => number;
  getOffsetAdjustment: () => number;
  commitOffsetAdjustment: (count: number) => void;
  resetPagination: () => void;
  fetchPage: (params: {
    offset: number;
    limit: number;
  }) => Promise<ConversationPage<TItem, TMetadata>>;
  mapItem: (item: TItem) => TThread;
  onMetadata: (metadata: TMetadata) => void;
}

interface ConversationThreadPageOptions {
  after?: string;
}

export interface ConversationThreadPage<TThread> {
  threads: TThread[];
  nextCursor?: string;
}

interface ConversationDeletionLifecycleOptions {
  pendingPageLoad: Promise<void> | null;
  deleteConversation: () => void | Promise<void>;
  recordDeletedLoadedItem: () => void;
}

export const runConversationDeletionLifecycle = async ({
  pendingPageLoad,
  deleteConversation,
  recordDeletedLoadedItem,
}: ConversationDeletionLifecycleOptions): Promise<void> => {
  await pendingPageLoad;
  await deleteConversation();
  recordDeletedLoadedItem();
};

const parseOffset = (after: string | undefined, pageSize: number): number => {
  if (after === undefined) return 0;

  const offset = Number(after);
  return Number.isSafeInteger(offset) &&
    offset >= 0 &&
    offset <= Number.MAX_SAFE_INTEGER - pageSize
    ? offset
    : 0;
};

export const createConversationThreadPageLoader = <
  TItem,
  TThread,
  TMetadata extends { total: number } = { total: number },
>({
  pageSize,
  takeNextPageSize,
  getOffsetAdjustment,
  commitOffsetAdjustment,
  resetPagination,
  fetchPage,
  mapItem,
  onMetadata,
}: ConversationThreadPageLoaderOptions<TItem, TThread, TMetadata>) => {
  return async ({ after }: ConversationThreadPageOptions = {}): Promise<
    ConversationThreadPage<TThread>
  > => {
    // assistant-ui starts loading before the sidebar has committed and can be
    // measured. Bootstrap the runtime without fetching so the mounted list can
    // choose a first-page size from the real viewport in the same frame.
    if (after === undefined) {
      resetPagination();
      return { threads: [], nextCursor: "0" };
    }

    const limit = takeNextPageSize(pageSize);
    const requestedOffset = parseOffset(after, limit);
    const offsetAdjustment = Math.min(requestedOffset, getOffsetAdjustment());
    const offset = requestedOffset - offsetAdjustment;
    const data = await fetchPage({ offset, limit });
    commitOffsetAdjustment(offsetAdjustment);
    onMetadata(data.metadata);
    const nextOffset = offset + data.items.length;

    return {
      threads: data.items.map(mapItem),
      nextCursor:
        nextOffset < data.metadata.total ? String(nextOffset) : undefined,
    };
  };
};
