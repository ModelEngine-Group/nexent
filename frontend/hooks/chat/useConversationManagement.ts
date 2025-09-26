import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { conversationService } from "@/services/conversationService";
import { ConversationListItem } from "@/types/chat";
import log from "@/lib/logger";

export const useConversationManagement = () => {
  const { t } = useTranslation("common");
  
  // Conversation state
  const [conversationId, setConversationId] = useState<number>(0);
  const [conversationTitle, setConversationTitle] = useState(
    t("chatInterface.newConversation")
  );
  const [conversationList, setConversationList] = useState<
    ConversationListItem[]
  >([]);
  const [selectedConversationId, setSelectedConversationId] = useState<
    number | null
  >(null);
  const [isNewConversation, setIsNewConversation] = useState(true);
  const [conversationLoadError, setConversationLoadError] = useState<{
    [conversationId: number]: string;
  }>({});

  // Refs
  const currentSelectedConversationRef = useRef<number | null>(null);
  const initialized = useRef(false);

  // Ensure currentSelectedConversationRef is synchronized with selectedConversationId
  useEffect(() => {
    currentSelectedConversationRef.current = selectedConversationId;
  }, [selectedConversationId]);

  // Fetch conversation list
  const fetchConversationList = async (): Promise<ConversationListItem[]> => {
    try {
      const dialogHistory = await conversationService.getList();
      // Sort by creation time, newest first
      dialogHistory.sort((a, b) => b.create_time - a.create_time);
      setConversationList(dialogHistory);
      return dialogHistory;
    } catch (error) {
      log.error(t("chatInterface.errorFetchingConversationList"), error);
      throw error;
    }
  };

  // Handle new conversation
  const handleNewConversation = () => {
    setConversationId(-1);
    setSelectedConversationId(null);
    setConversationTitle(t("chatInterface.newConversation"));
    setIsNewConversation(true);
    currentSelectedConversationRef.current = null;
  };

  // Handle conversation selection
  const handleConversationSelect = async (dialog: ConversationListItem) => {
    // Immediately set conversation state, avoid flashing new conversation interface
    setSelectedConversationId(dialog.conversation_id);
    setConversationId(dialog.conversation_id);
    setConversationTitle(dialog.conversation_title);

    // Update ref to track current selected conversation
    currentSelectedConversationRef.current = dialog.conversation_id;
    setIsNewConversation(false);
  };

  // Update conversation title
  const updateConversationTitle = async (dialogId: number, title: string) => {
    try {
      await conversationService.rename(dialogId, title);
      await fetchConversationList();

      if (selectedConversationId === dialogId) {
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
    conversationId,
    conversationTitle,
    conversationList,
    selectedConversationId,
    isNewConversation,
    conversationLoadError,
    
    // Refs
    currentSelectedConversationRef,
    initialized,
    
    // Methods
    fetchConversationList,
    handleNewConversation,
    handleConversationSelect,
    updateConversationTitle,
    clearConversationLoadError,
    setConversationLoadErrorForId,
    
    // Setters (for internal use by components)
    setConversationId,
    setSelectedConversationId,
    setConversationTitle,
    setIsNewConversation,
  };
};
