interface ConversationLoadState {
  hasMore: boolean;
  isLoading: boolean;
  isNearBottom: boolean;
}

export const shouldLoadNextConversationPage = (
  state: ConversationLoadState
): boolean => state.hasMore && !state.isLoading && state.isNearBottom;

export const isConversationListNearBottom = (
  scrollHeight: number,
  scrollTop: number,
  clientHeight: number,
  threshold = 80
): boolean => scrollHeight - scrollTop - clientHeight <= threshold;

interface ConversationScrollRequestState {
  hasMore: boolean;
  isLoading: boolean;
  scrollHeight: number;
  scrollTop: number;
  clientHeight: number;
  hasUserIntent: boolean;
  isScrollingDown: boolean;
}

export const shouldRequestConversationPageFromScroll = (
  state: ConversationScrollRequestState
): boolean =>
  state.hasUserIntent &&
  state.isScrollingDown &&
  shouldLoadNextConversationPage({
    hasMore: state.hasMore,
    isLoading: state.isLoading,
    isNearBottom: isConversationListNearBottom(
      state.scrollHeight,
      state.scrollTop,
      state.clientHeight
    ),
  });

interface ConversationPageRequestState {
  hasMore: boolean;
  isLoading: boolean;
  clientHeight: number;
  scrollHeight: number;
  rowHeight: number;
  isLoadRequested: boolean;
  regularPageSize: number;
}

export interface ConversationPageRequest {
  limit: number;
  reason: "viewport-fill" | "scroll";
}

export const getConversationPageRequest = (
  state: ConversationPageRequestState
): ConversationPageRequest | null => {
  if (
    !state.hasMore ||
    state.isLoading ||
    state.clientHeight <= 0 ||
    state.rowHeight <= 0
  ) {
    return null;
  }

  if (state.scrollHeight <= state.clientHeight) {
    const missingHeight = state.clientHeight - state.scrollHeight;
    return {
      limit: Math.min(100, Math.ceil(missingHeight / state.rowHeight) + 1),
      reason: "viewport-fill",
    };
  }

  return state.isLoadRequested
    ? {
        limit: Math.max(1, state.regularPageSize),
        reason: "scroll",
      }
    : null;
};
