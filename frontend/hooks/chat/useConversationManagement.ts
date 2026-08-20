import type React from "react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type {
  InfiniteData,
  UseInfiniteQueryResult,
} from "@tanstack/react-query";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CONVERSATION_PAGE_SIZE,
  conversationService,
} from "@/services/conversationService";
import {
  ConversationListItem,
  ConversationListMetadata,
} from "@/types/conversation";
import log from "@/lib/logger";
import { getConversationDateBoundaries } from "@/lib/conversationViewport";

const CONVERSATION_LIST_QUERY_KEY = ["conversations", "legacy-chat"] as const;
type ConversationListData = InfiniteData<ConversationListItem[], number>;

/**
 * Return type of useConversationManagement hook.
 * Use this type when passing conversation management state/handlers between parent and child components.
 */
export interface ConversationManagement {
  conversationTitle: string;
  conversationList: ConversationListItem[];
  selectedConversationId: number | null;
  isNewConversation: boolean;
  conversationLoadError: Record<number, string>;
  conversationListQuery: UseInfiniteQueryResult<ConversationListData, Error>;
  fetchConversationList: () => Promise<ConversationListItem[]>;
  invalidateConversationList: () => void;
  hasNextPage: boolean;
  fetchNextPage: () => Promise<void>;
  conversationMetadata?: ConversationListMetadata;
  resolveInitialPageSize: (limit: number) => void;
  prependConversation: (
    conversationId: number,
    title: string,
    agentId?: number | null
  ) => void;
  updateConversationAgentId: (
    conversationId: number,
    agentId: number | null
  ) => void;
  handleNewConversation: () => void;
  handleConversationSelect: (conversation: ConversationListItem) => Promise<void>;
  updateConversationTitle: (conversationId: number, title: string) => Promise<void>;
  clearConversationLoadError: (conversationId: number) => void;
  setConversationLoadErrorForId: (
    conversationId: number,
    error: string
  ) => void;
  setSelectedConversationId: React.Dispatch<React.SetStateAction<number | null>>;
  setConversationTitle: React.Dispatch<React.SetStateAction<string>>;
  setIsNewConversation: React.Dispatch<React.SetStateAction<boolean>>;
}

export const useConversationManagement = (): ConversationManagement => {
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();
  const [dateBoundaries] = useState(getConversationDateBoundaries);
  const [initialPageSize, setInitialPageSize] = useState<number | null>(null);
  const resolveInitialPageSize = useCallback(
    (limit: number) => setInitialPageSize(limit),
    []
  );
  const conversationListQueryKey = useMemo(
    () => [...CONVERSATION_LIST_QUERY_KEY, initialPageSize] as const,
    [initialPageSize]
  );
  const metadataQuery = useQuery({
    queryKey: ["conversation-list-metadata", dateBoundaries],
    queryFn: () =>
      conversationService.getListMetadata(
        dateBoundaries.todayStartMs,
        dateBoundaries.weekStartMs
      ),
    staleTime: 30_000,
    gcTime: 0,
  });

  const conversationListQuery = useInfiniteQuery<
    ConversationListItem[],
    Error,
    ConversationListData,
    typeof conversationListQueryKey,
    number
  >({
    queryKey: conversationListQueryKey,
    queryFn: async ({ pageParam }): Promise<ConversationListItem[]> => {
      const dialogHistory = await conversationService.getList({
        offset: pageParam,
        limit: pageParam === 0 ? initialPageSize! : CONVERSATION_PAGE_SIZE,
      });
      dialogHistory.sort((a, b) => b.create_time - a.create_time);
      return dialogHistory;
    },
    initialPageParam: 0,
    getNextPageParam: (_lastPage, allPages) => {
      const loaded = allPages.reduce((count, page) => count + page.length, 0);
      return loaded < (metadataQuery.data?.total ?? 0) ? loaded : undefined;
    },
    enabled:
      initialPageSize !== null &&
      metadataQuery.isSuccess &&
      (metadataQuery.data?.total ?? 0) > 0,
    staleTime: 30_000,
    gcTime: 0,
  });

  const conversationList = Array.from(
    new Map(
      (conversationListQuery.data?.pages.flat() ?? [])
        .sort((a, b) => b.create_time - a.create_time)
        .map((conversation) => [conversation.conversation_id, conversation])
    ).values()
  );

  const fetchConversationList = async (): Promise<ConversationListItem[]> => {
    await metadataQuery.refetch();
    const result = await conversationListQuery.refetch();
    if (result.error) {
      log.error(t("chatInterface.errorFetchingConversationList"), result.error);
      throw result.error;
    }
    return Array.from(
      new Map(
        (result.data?.pages.flat() ?? [])
          .sort((a, b) => b.create_time - a.create_time)
          .map((conversation) => [conversation.conversation_id, conversation])
      ).values()
    );
  };

  const invalidateConversationList = () => {
    void queryClient.invalidateQueries({
      queryKey: ["conversation-list-metadata"],
    });
    void queryClient.invalidateQueries({ queryKey: CONVERSATION_LIST_QUERY_KEY });
  };

  const fetchNextPage = async (): Promise<void> => {
    const result = await conversationListQuery.fetchNextPage();
    if (result.error) {
      throw result.error;
    }
  };

  // Conversation state: null = no selection / new conversation, number = current conversation id
  const [conversationTitle, setConversationTitle] = useState(
    t("chatInterface.newConversation")
  );
  const [selectedConversationId, setSelectedConversationId] = useState<
    number | null
  >(null);
  const [isNewConversation, setIsNewConversation] = useState(true);
  const [conversationLoadError, setConversationLoadError] = useState<{
    [conversationId: number]: string;
  }>({});

  // Refs

  // Handle new conversation
  const handleNewConversation = () => {
    setSelectedConversationId(null);
    setConversationTitle(t("chatInterface.newConversation"));
    setIsNewConversation(true);
  };

  // Prepend a newly created conversation to the sidebar list so it appears
  // immediately (without waiting for a refetch).
  const prependConversation = useCallback(
    (conversationId: number, title: string, agentId?: number | null) => {
      queryClient.setQueryData<ConversationListData>(
        conversationListQueryKey,
        (prev) => {
          const existing = prev?.pages.flat() ?? [];
          // Avoid duplicates if the backend has already populated it.
          if (existing.some((c) => c.conversation_id === conversationId)) {
            return prev;
          }
          const now = Date.now();
          const newItem: ConversationListItem = {
            conversation_id: conversationId,
            conversation_title: title,
            agent_id: agentId ?? null,
            create_time: now,
            update_time: now,
          };
          if (!prev) {
            return { pages: [[newItem]], pageParams: [0] };
          }
          return {
            ...prev,
            pages: [
              [newItem, ...(prev.pages[0] ?? [])],
              ...prev.pages.slice(1),
            ],
          };
        }
      );
    },
    [conversationListQueryKey, queryClient]
  );

  const updateConversationAgentId = useCallback(
    (conversationId: number, agentId: number | null) => {
      queryClient.setQueryData<ConversationListData>(
        conversationListQueryKey,
        (prev) => {
          if (!prev) {
            return prev;
          }
          return {
            ...prev,
            pages: prev.pages.map((page) =>
              page.map((conversation) =>
                conversation.conversation_id === conversationId
                  ? { ...conversation, agent_id: agentId }
                  : conversation
              )
            ),
          };
        }
      );
    },
    [conversationListQueryKey, queryClient]
  );

  // Handle conversation selection
  const handleConversationSelect = async (
    conversation: ConversationListItem
  ) => {
    setSelectedConversationId(conversation.conversation_id);
    setConversationTitle(conversation.conversation_title);
    setIsNewConversation(false);
  };

  // Update conversation title
  const updateConversationTitle = async (
    conversationId: number,
    title: string
  ) => {
    try {
      await conversationService.rename(conversationId, title);
      await fetchConversationList();

      if (selectedConversationId === conversationId) {
        setConversationTitle(title);
      }
    } catch (error) {
      log.error(t("chatInterface.errorUpdatingTitle"), error);
    }
  };
  // Clear conversation load error
  const clearConversationLoadError = (conversationId: number) => {
    setConversationLoadError((prev) => {
      const newErrors = { ...prev };
      delete newErrors[conversationId];
      return newErrors;
    });
  };

  // Set conversation load error
  const setConversationLoadErrorForId = (
    conversationId: number,
    error: string
  ) => {
    setConversationLoadError((prev) => ({
      ...prev,
      [conversationId]: error,
    }));
  };

  return {
    // State (read-only)
    conversationTitle,
    conversationList,
    selectedConversationId,
    isNewConversation,
    conversationLoadError,
    conversationListQuery,

    // Methods
    fetchConversationList,
    invalidateConversationList,
    hasNextPage: conversationListQuery.hasNextPage,
    fetchNextPage,
    conversationMetadata: metadataQuery.data,
    resolveInitialPageSize,
    prependConversation,
    updateConversationAgentId,
    handleNewConversation,
    handleConversationSelect,
    updateConversationTitle,
    clearConversationLoadError,
    setConversationLoadErrorForId,

    // Setters (for internal use by components)
    setSelectedConversationId,
    setConversationTitle,
    setIsNewConversation,
  };
};
