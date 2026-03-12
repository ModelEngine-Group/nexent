import type React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { UseQueryResult } from "@tanstack/react-query";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { conversationService } from "@/services/conversationService";
import { ConversationListItem } from "@/types/chat";
import log from "@/lib/logger";

const CONVERSATION_LIST_QUERY_KEY = ["conversations"] as const;

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
  conversationListQuery: UseQueryResult<ConversationListItem[], Error>;
  fetchConversationList: () => Promise<ConversationListItem[]>;
  invalidateConversationList: () => void;
  handleNewConversation: () => void;
  handleConversationSelect: (conversation: ConversationListItem) => Promise<void>;
  updateConversationTitle: (conversationId: number, title: string) => Promise<void>;
  clearConversationLoadError: (conversationId: number) => void;
  setConversationLoadErrorForId: (conversationId: number, error: string) => void;
  setSelectedConversationId: React.Dispatch<React.SetStateAction<number | null>>;
  setConversationTitle: React.Dispatch<React.SetStateAction<string>>;
  setIsNewConversation: React.Dispatch<React.SetStateAction<boolean>>;
}

export const useConversationManagement = (): ConversationManagement => {
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();

  const conversationListQuery = useQuery({
    queryKey: CONVERSATION_LIST_QUERY_KEY,
    queryFn: async (): Promise<ConversationListItem[]> => {
      const dialogHistory = await conversationService.getList();
      dialogHistory.sort((a, b) => b.create_time - a.create_time);
      return dialogHistory;
    },
    staleTime: 30_000,
  });

  const conversationList = conversationListQuery.data ?? [];

  const fetchConversationList = async (): Promise<ConversationListItem[]> => {
    const result = await conversationListQuery.refetch();
    if (result.error) {
      log.error(t("chatInterface.errorFetchingConversationList"), result.error);
      throw result.error;
    }
    return result.data ?? [];
  };

  const invalidateConversationList = () => queryClient.invalidateQueries({ queryKey: CONVERSATION_LIST_QUERY_KEY });

  // Conversation state: null = no selection / new conversation, number = current conversation id
  const [conversationTitle, setConversationTitle] = useState(t("chatInterface.newConversation"));
  const [selectedConversationId, setSelectedConversationId] = useState<number | null>(null);
  const [isNewConversation, setIsNewConversation] = useState(true);
  const [conversationLoadError, setConversationLoadError] = useState<{[conversationId: number]: string;}>({});

  // Refs

  // Handle new conversation
  const handleNewConversation = () => {
    setSelectedConversationId(null);
    setConversationTitle(t("chatInterface.newConversation"));
    setIsNewConversation(true);
  };

  // Handle conversation selection
  const handleConversationSelect = async (conversation: ConversationListItem) => {
    setSelectedConversationId(conversation.conversation_id);
    setConversationTitle(conversation.conversation_title);
    setIsNewConversation(false);
  };

  // Update conversation title
  const updateConversationTitle = async (conversationId: number, title: string) => {
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
  const setConversationLoadErrorForId = (conversationId: number, error: string) => {
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
