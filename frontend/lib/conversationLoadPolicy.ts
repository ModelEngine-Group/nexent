interface ConversationLoadState {
  hasMore: boolean;
  isLoading: boolean;
  isNearBottom: boolean;
  hasDownwardUserIntent: boolean;
}

export const shouldLoadNextConversationPage = (
  state: ConversationLoadState
): boolean =>
  state.hasMore &&
  !state.isLoading &&
  state.isNearBottom &&
  state.hasDownwardUserIntent;

export const isConversationListNearBottom = (
  scrollHeight: number,
  scrollTop: number,
  clientHeight: number,
  threshold = 80
): boolean => scrollHeight - scrollTop - clientHeight <= threshold;

interface ConversationPageContinuationState {
  hasMore: boolean;
  loadedBefore: number;
  loadedAfter: number;
  isNearLoadedBoundary: boolean;
}

export const shouldContinueConversationPageLoading = (
  state: ConversationPageContinuationState
): boolean =>
  state.hasMore &&
  state.loadedAfter > state.loadedBefore &&
  state.isNearLoadedBoundary;
