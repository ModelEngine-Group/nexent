"use client";

import type React from "react";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { v4 as uuidv4 } from "uuid";
import { useTranslation } from "react-i18next";

import { ROLE_ASSISTANT } from "@/const/agentConfig";
import { MESSAGE_ROLES } from "@/const/chatConfig";
import { useConfig } from "@/hooks/useConfig";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { conversationService } from "@/services/conversationService";
import { storageService, convertImageUrlToApiUrl } from "@/services/storageService";
import { useConversationManagement } from "@/hooks/chat/useConversationManagement";

import { ChatSidebar } from "../components/chatLeftSidebar";
import { FilePreview } from "@/types/chat";
import { ChatHeader } from "../components/chatHeader";
import { ChatRightPanel } from "../components/chatRightPanel";
import { ChatStreamMain } from "../streaming/chatStreamMain";

import {
  preprocessAttachments,
  handleFileUpload as preProcessHandleFileUpload,
  handleImageUpload as preProcessHandleImageUpload,
  uploadAttachments,
  createMessageAttachments,
  cleanupAttachmentUrls,
} from "@/app/chat/internal/chatPreprocess";
import { Tooltip, TooltipProvider } from "@/components/ui/tooltip";

import { ConversationListItem, ApiConversationDetail } from "@/types/chat";
import { ChatMessageType } from "@/types/chat";
import { handleStreamResponse } from "@/app/chat/streaming/chatStreamHandler";
import {
  extractUserMsgFromResponse,
  extractAssistantMsgFromResponse,
} from "./extractMsgFromHistoryResponse";

import { X } from "lucide-react";
import log from "@/lib/logger";

const stepIdCounter = { current: 0 };

// Get internationalization key based on message type
const getI18nKeyByType = (type: string): string => {
  const typeToKeyMap: Record<string, string> = {
    "progress": "chatInterface.parsingFileWithProgress",
    "truncation": "chatInterface.fileTruncated",
  };
  return typeToKeyMap[type] || "";
};

export function ChatInterface() {
  const router = useRouter();
  const { user } = useAuthorizationContext();
  const { isSpeedMode } = useDeployment();
  const [input, setInput] = useState("");
  // Replace the original messages state
  const [sessionMessages, setSessionMessages] = useState<{
    [conversationId: number]: ChatMessageType[];
  }>({});
  const [isSwitchedConversation, setIsSwitchedConversation] = useState(false); // Add conversation switching tracking state
  const [isLoading, setIsLoading] = useState(false);
  const { t } = useTranslation("common");

  // Use conversation management hook
  const conversationManagement = useConversationManagement();
  const [openDropdownId, setOpenDropdownId] = useState<string | null>(null);
  const { appConfig } = useConfig();

  // For each conversation, maintain independent SSE connections and states
  const [streamingConversations, setStreamingConversations] = useState<
    Set<number>
  >(new Set());
  const conversationControllersRef = useRef<Map<number, AbortController>>(
    new Map()
  );
  const conversationTimeoutsRef = useRef<Map<number, NodeJS.Timeout>>(
    new Map()
  );

  // Place the declaration of currentMessages after the definition of selectedConversationId
  // If a historical conversation is being loaded and there are no cached messages, return an empty array to avoid displaying error content
  const currentMessages = conversationManagement.selectedConversationId
    ? sessionMessages[conversationManagement.selectedConversationId] || []
    : [];

  // Monitor changes in currentMessages
  // Calculate if the current conversation is streaming
  const isCurrentConversationStreaming =
    conversationManagement.conversationId && conversationManagement.conversationId !== -1
      ? streamingConversations.has(conversationManagement.conversationId)
      : false;

  const [viewingImage, setViewingImage] = useState<string | null>(null);

  // Add attachment state management
  const [attachments, setAttachments] = useState<FilePreview[]>([]);
  const [fileUrls, setFileUrls] = useState<{ [id: string]: string }>({});

  const [isStreaming, setIsStreaming] = useState(false); // Add streaming state
  const abortControllerRef = useRef<AbortController | null>(null); // Add AbortController reference
  const timeoutRef = useRef<NodeJS.Timeout | null>(null); // Add timeout reference

  // Add sidebar state control
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // Add a state to track if we're loading a historical conversation
  const [isLoadingHistoricalConversation, setIsLoadingHistoricalConversation] =
    useState(false);

  // Add a state to track completed conversations that haven't been viewed yet
  const [completedConversations, setCompletedConversations] = useState<
    Set<number>
  >(new Set());

  // Add a ref to track the currently selected conversation ID for real-time access
  const currentSelectedConversationRef = useRef<number | null>(null);

  // Ensure right sidebar is closed by default
  const [showRightPanel, setShowRightPanel] = useState(false);

  const [selectedMessageId, setSelectedMessageId] = useState<
    string | undefined
  >();

  // Add force scroll to bottom state control
  const [shouldScrollToBottom, setShouldScrollToBottom] = useState(false);

  // Add agent selection state
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  useEffect(() => {
    const agentId = sessionStorage.getItem("selectedAgentId");
    // Set selected agent ID from sessionStorage if it exists
    if (agentId) {
      setSelectedAgentId(agentId);
      sessionStorage.removeItem("selectedAgentId");
    }
  },[]);

  // Reset scroll to bottom state
  useEffect(() => {
    if (shouldScrollToBottom) {
      // Give enough time for scrolling to complete, then reset state
      const timer = setTimeout(() => {
        setShouldScrollToBottom(false);
      }, 1200); // Slightly longer than the last scroll delay in ChatStreamMain

      return () => clearTimeout(timer);
    }
  }, [shouldScrollToBottom]);

  // Add attachment cleanup function - cleanup URLs when component unmounts
  useEffect(() => {
    return () => {
      // Use preprocessing function to cleanup URLs
      cleanupAttachmentUrls(attachments, fileUrls);
    };
  }, [attachments, fileUrls]);

  // Handle file upload
  const handleFileUpload = (file: File) => {
    return preProcessHandleFileUpload(file, setFileUrls, t);
  };

  // Handle image upload
  const handleImageUpload = (file: File) => {
    preProcessHandleImageUpload(file, t);
  };

  // Add attachment management function
  const handleAttachmentsChange = (newAttachments: FilePreview[]) => {
    setAttachments(newAttachments);
  };

  // Define sidebar toggle function
  const toggleSidebar = () => {
    setSidebarOpen(!sidebarOpen);
  };

  // Handle right panel toggle - keep it simple and clear
  const toggleRightPanel = () => {
    setShowRightPanel(!showRightPanel);
  };

  useEffect(() => {
    if (!conversationManagement.initialized.current) {
      conversationManagement.initialized.current = true;

      // Get conversation history list, but don't auto-select the latest conversation
      conversationManagement.fetchConversationList()
        .then((dialogData) => {
          // Create new conversation by default regardless of history
          handleNewConversation();
        })
        .catch((err) => {
          log.error(t("chatInterface.errorFetchingConversationList"), err);
          // Create new conversation even if getting conversation list fails
          handleNewConversation();
        });
    }
  }, [appConfig]); // Add appConfig as dependency

  // Add useEffect to listen for conversationId changes, ensure right sidebar is always closed when conversation switches
  useEffect(() => {
    // Ensure right sidebar is reset to closed state whenever conversation ID changes
    setSelectedMessageId(undefined);
    setShowRightPanel(false);
  }, [conversationManagement.conversationId]);

  // Helper function to clear completed conversation indicator
  const clearCompletedIndicator = useCallback(() => {
    if (
      conversationManagement.conversationId &&
      conversationManagement.conversationId !== -1
    ) {
      setCompletedConversations((prev) => {
        // Use functional update to avoid dependency on completedConversations
        if (prev.has(conversationManagement.conversationId)) {
          const newSet = new Set(prev);
          newSet.delete(conversationManagement.conversationId);
          return newSet;
        }
        return prev;
      });
    }
  }, [conversationManagement.conversationId]);

  // Add useEffect to clear completed conversation indicator when user is viewing the current conversation
  useEffect(() => {
    // If current conversation is in completedConversations, clear it when user is viewing it
    clearCompletedIndicator();
  }, [conversationManagement.conversationId, clearCompletedIndicator]);

  // Add click event listener to clear completed conversation indicator when user clicks anywhere on the page
  useEffect(() => {
    const handlePageClick = (e: MouseEvent) => {
      // Clear completed indicator when user clicks anywhere on the page
      clearCompletedIndicator();
    };

    // Add click event listener to the document
    document.addEventListener('click', handlePageClick, true);

    return () => {
      document.removeEventListener('click', handlePageClick, true);
    };
  }, [clearCompletedIndicator]);


  // Clear all timers and requests when component unmounts
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        try {
          abortControllerRef.current.abort(t("chatInterface.componentUnmount"));
        } catch (error) {
          log.error(t("chatInterface.errorCancelingRequest"), error);
        }
        abortControllerRef.current = null;
      }

      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
    };
  }, []);

  const handleSend = async () => {
    if (!input.trim() && attachments.length === 0) return; // Allow sending attachments only, without text content

    // Flag to track if we should reset button states in finally block
    let shouldResetButtonStates = true;

    // If in new conversation state, switch to conversation state after sending message
    if (conversationManagement.isNewConversation) {
      conversationManagement.setIsNewConversation(false);
    }

    // Ensure right sidebar doesn't auto-expand when sending new message
    setSelectedMessageId(undefined);
    setShowRightPanel(false);

    // Handle user message content
    const userMessageId = uuidv4();
    const userMessageContent = input.trim();

    // Get current conversation ID
    let currentConversationId = conversationManagement.conversationId;

    // Ensure ref reflects the current conversation state
    if (currentConversationId && currentConversationId !== -1) {
      conversationManagement.currentSelectedConversationRef.current = currentConversationId;
    }

    // Prepare attachment information
    // Handle file upload
    let uploadedFileUrls: Record<string, string> = {};
    let objectNames: Record<string, string> = {}; // Add object name mapping

    if (attachments.length > 0) {
      // Show loading state
      setIsLoading(true);

      // Use preprocessing function to upload attachments
      const uploadResult = await uploadAttachments(attachments, t);
      uploadedFileUrls = uploadResult.uploadedFileUrls;
      objectNames = uploadResult.objectNames; // Get object name mapping
    }

    // Use preprocessing function to create message attachments
    const messageAttachments = createMessageAttachments(
      attachments,
      uploadedFileUrls,
      fileUrls
    );

    // Create user message object
    const userMessage: ChatMessageType = {
      id: userMessageId,
      role: MESSAGE_ROLES.USER,
      content: userMessageContent,
      timestamp: new Date(),
      attachments:
        messageAttachments.length > 0 ? messageAttachments : undefined,
    };

    // Clear input box and attachments
    setInput("");
    setAttachments([]);

    // Create initial AI reply message
    const assistantMessageId = uuidv4();
    const initialAssistantMessage: ChatMessageType = {
      id: assistantMessageId,
      role: ROLE_ASSISTANT,
      content: "",
      timestamp: new Date(),
      isComplete: false,
      steps: [],
    };

    // Send message and scroll to bottom
    setShouldScrollToBottom(true);

    setIsLoading(true);
    setIsStreaming(true); // Set streaming state to true

    // Create independent AbortController for current conversation
    const currentController = new AbortController();

    try {
      // Check if need to create new conversation
      if (!currentConversationId || currentConversationId === -1) {
        // If no session ID or ID is -1, create new conversation first
        try {
          const createData = await conversationService.create(
            t("chatInterface.newConversation")
          );
          currentConversationId = createData.conversation_id;

          // Update current session state
          conversationManagement.setConversationId(currentConversationId);
          conversationManagement.setSelectedConversationId(currentConversationId);
          // Update ref to track current selected conversation
          conversationManagement.currentSelectedConversationRef.current = currentConversationId;
          conversationManagement.setConversationTitle(
            createData.conversation_title || t("chatInterface.newConversation")
          );

          // After creating new conversation, add it to streaming list
          setStreamingConversations((prev) => {
            const newSet = new Set(prev).add(currentConversationId);

            return newSet;
          });

          // Refresh conversation list
          try {
            const dialogList = await conversationManagement.fetchConversationList();
            const newDialog = dialogList.find(
              (dialog) => dialog.conversation_id === currentConversationId
            );
            if (newDialog) {
              conversationManagement.setSelectedConversationId(currentConversationId);
            }
          } catch (error) {
            log.error(
              t("chatInterface.refreshDialogListFailedButContinue"),
              error
            );
          }
        } catch (error) {
          log.error(
            t("chatInterface.createDialogFailedButContinue"),
            error
          );
          // Reset button states when conversation creation fails
          setIsLoading(false);
          setIsStreaming(false);
          return;
        }
      }

      // Ensure valid conversation ID before registering controller and streaming state
      if (currentConversationId && currentConversationId !== -1) {
        conversationControllersRef.current.set(
          currentConversationId,
          currentController
        );
        setStreamingConversations((prev) => {
          const newSet = new Set(prev);
          newSet.add(currentConversationId);
          return newSet;
        });
      }

      // Now add messages after conversation is created/confirmed
      // 1. When sending user message, complete ChatMessageType fields
      setSessionMessages((prev) => ({
        ...prev,
        [currentConversationId]: [
          ...(prev[currentConversationId] || []),
          {
            ...userMessage,
            id: userMessage.id || uuidv4(),
            timestamp: userMessage.timestamp || new Date(),
            isComplete: userMessage.isComplete ?? true,
            steps: userMessage.steps || [],
            attachments: userMessage.attachments || [],
            images: userMessage.images || [],
          },
        ],
      }));

      // 2. When adding AI reply message, complete ChatMessageType fields
      setSessionMessages((prev) => ({
        ...prev,
        [currentConversationId]: [
          ...(prev[currentConversationId] || []),
          {
            ...initialAssistantMessage,
            id: initialAssistantMessage.id || uuidv4(),
            timestamp: initialAssistantMessage.timestamp || new Date(),
            isComplete: initialAssistantMessage.isComplete ?? false,
            steps: initialAssistantMessage.steps || [],
            attachments: initialAssistantMessage.attachments || [],
            images: initialAssistantMessage.images || [],
          },
        ],
      }));

      // If there are attachment files, skip preprocessing (no API call, no UI prompts)
      let finalQuery = userMessage.content;
      // Declare a variable to save file description information
      let fileDescriptionsMap: Record<string, string> = {};

      if (attachments.length > 0) {
        // Skip preprocessing - directly use original content
        // No preprocessing UI will be shown
        const result = await preprocessAttachments(
          userMessage.content,
          attachments,
          currentController.signal,
          () => {}, // Empty progress callback - won't be called
          t,
          currentConversationId
        );

        finalQuery = result.finalQuery;
        fileDescriptionsMap = result.fileDescriptions || {};
      }

      // Send request to backend API, add signal parameter
      const runAgentParams: any = {
        query: finalQuery, // Use preprocessed query or original query
        conversation_id: currentConversationId,
        is_set: isSwitchedConversation || currentMessages.length <= 1,
        history: currentMessages
          .filter((msg) => msg.id !== userMessage.id)
          .map((msg) => ({
            role: msg.role,
            content:
              msg.role === ROLE_ASSISTANT
                ? msg.finalAnswer?.trim() || msg.content || ""
                : msg.content || "",
          })),
        minio_files:
          messageAttachments.length > 0
            ? messageAttachments.map((attachment) => {
                // Get file description
                let description = "";
                if (attachment.name in fileDescriptionsMap) {
                  description = fileDescriptionsMap[attachment.name];
                }

                return {
                  object_name: objectNames[attachment.name] || "",
                  name: attachment.name,
                  type: attachment.type,
                  size: attachment.size,
                  url: uploadedFileUrls[attachment.name] || attachment.url,
                  description: description,
                };
              })
            : undefined, // Use complete attachment object structure
      };

      // Only add agent_id if it's not null
      if (selectedAgentId !== null) {
        runAgentParams.agent_id = Number(selectedAgentId);
      }

      const reader = await conversationService.runAgent(
        runAgentParams,
        currentController.signal
      );

      if (!reader) throw new Error("Response body is null");

      // Create dynamic setCurrentSessionMessages in handleSend function
      // setCurrentSessionMessages factory function
      const setCurrentSessionMessagesFactory =
        (
          targetConversationId: number
        ): React.Dispatch<React.SetStateAction<ChatMessageType[]>> =>
        (valueOrUpdater) => {
          setSessionMessages((prev) => {
            const prevArr = prev[targetConversationId] || [];
            let nextArr: ChatMessageType[];
            if (typeof valueOrUpdater === "function") {
              nextArr = (
                valueOrUpdater as (prev: ChatMessageType[]) => ChatMessageType[]
              )(prevArr);
            } else {
              nextArr = valueOrUpdater;
            }
            // Ensure new reference
            return {
              ...prev,
              [targetConversationId]: [...nextArr],
            };
          });
        };

      // Create resetTimeout function for current conversation
      const resetTimeout = () => {
        const timeout = conversationTimeoutsRef.current.get(
          currentConversationId
        );
        if (timeout) {
          clearTimeout(timeout);
        }
        const newTimeout = setTimeout(async () => {
          const controller = conversationControllersRef.current.get(
            currentConversationId
          );
          if (controller && !controller.signal.aborted) {
            try {
              controller.abort(t("chatInterface.requestTimeout"));

              setSessionMessages((prev) => {
                const newMessages = { ...prev };
                const lastMsg =
                  newMessages[currentConversationId]?.[
                    newMessages[currentConversationId].length - 1
                  ];
                if (lastMsg && lastMsg.role === ROLE_ASSISTANT) {
                  lastMsg.error = t("chatInterface.requestTimeoutRetry");
                  lastMsg.isComplete = true;
                  lastMsg.thinking = undefined;
                }
                return newMessages;
              });

              if (currentConversationId && currentConversationId !== -1) {
                try {
                  await conversationService.stop(currentConversationId);
                } catch (error) {
                  log.error(
                    t("chatInterface.stopTimeoutRequestFailed"),
                    error
                  );
                }
              }
            } catch (error) {
              log.error(t("chatInterface.errorCancelingRequest"), error);
            }
          }
          conversationTimeoutsRef.current.delete(currentConversationId);
        }, 120000);
        conversationTimeoutsRef.current.set(currentConversationId, newTimeout);
      };

      // Before processing streaming response, set an initial timeout first
      resetTimeout();

      // Call streaming processing function to handle response
      // Compatible with both function and direct assignment
      await handleStreamResponse(
        reader,
        setCurrentSessionMessagesFactory(currentConversationId),
        resetTimeout,
        stepIdCounter,
        setIsSwitchedConversation,
        conversationManagement.isNewConversation,
        conversationManagement.setConversationTitle,
        conversationManagement.fetchConversationList,
        currentConversationId,
        conversationService,
        false, // isDebug: false for normal chat mode
        t
      );

      // Reset all related states
      setIsLoading(false);
      setIsStreaming(false);

      // Clean up controller and timeout for current conversation
      conversationControllersRef.current.delete(currentConversationId);
      const timeout = conversationTimeoutsRef.current.get(
        currentConversationId
      );
      if (timeout) {
        clearTimeout(timeout);
        conversationTimeoutsRef.current.delete(currentConversationId);
      }

      // Remove from streaming list (only when conversationId is not -1)
      if (currentConversationId !== -1) {
        setStreamingConversations((prev) => {
          const newSet = new Set(prev);
          newSet.delete(currentConversationId);
          return newSet;
        });

        // When conversation is completed, only add to completed conversation list when user is not in current conversation interface
        // Use ref to get the actual conversation the user is in
        const currentUserConversation = currentSelectedConversationRef.current;
        if (currentUserConversation !== currentConversationId) {
          setCompletedConversations((prev) => {
            const newSet = new Set(prev);
            newSet.add(currentConversationId);
            return newSet;
          });
        }
      }

      // Note: Save operation is already implemented in agent run API, no need to save again in frontend
    } catch (error) {
      // If user actively canceled, don't show error message
      const err = error as Error;
      if (err.name === "AbortError") {
        setSessionMessages((prev) => {
          const newMessages = { ...prev };
          const lastMsg =
            newMessages[currentConversationId]?.[
              newMessages[currentConversationId].length - 1
            ];
          if (lastMsg && lastMsg.role === ROLE_ASSISTANT) {
            lastMsg.content = t("chatInterface.conversationStopped");
            lastMsg.isComplete = true;
            lastMsg.thinking = undefined; // Explicitly clear thinking state
          }
          return newMessages;
        });
      } else {
        log.error(t("chatInterface.errorLabel"), error);
        // Show user-friendly error message instead of technical error details
        const errorMessage = t("chatInterface.errorProcessingRequest");
        setSessionMessages((prev) => {
          const newMessages = { ...prev };
          const lastMsg =
            newMessages[currentConversationId]?.[
              newMessages[currentConversationId].length - 1
            ];
          if (lastMsg && lastMsg.role === ROLE_ASSISTANT) {
            lastMsg.content = errorMessage;
            lastMsg.isComplete = true;
            lastMsg.error = errorMessage;
            lastMsg.thinking = undefined; // Explicitly clear thinking state
          }
          return newMessages;
        });
      }

      setIsLoading(false);
      setIsStreaming(false);

      // Clean up controller and timeout for current conversation
      conversationControllersRef.current.delete(currentConversationId);
      const timeout = conversationTimeoutsRef.current.get(
        currentConversationId
      );
      if (timeout) {
        clearTimeout(timeout);
        conversationTimeoutsRef.current.delete(currentConversationId);
      }

      // Remove from streaming list (only when conversationId is not -1)
      if (currentConversationId !== -1) {
        setStreamingConversations((prev) => {
          const newSet = new Set(prev);
          newSet.delete(currentConversationId);
          return newSet;
        });

        // When conversation is completed, only add to completed conversation list when user is not in current conversation interface
        // Use ref to get the actual conversation the user is in
        const currentUserConversation = currentSelectedConversationRef.current;
        if (currentUserConversation !== currentConversationId) {
          setCompletedConversations((prev) => {
            const newSet = new Set(prev);
            newSet.add(currentConversationId);
            return newSet;
          });
        }
      }
    } finally {
      // Only reset button states if we should (not when preprocessing fails)
      if (shouldResetButtonStates) {
        setIsLoading(false);
        setIsStreaming(false);
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleNewConversation = async () => {
    // When creating new conversation, keep all existing SSE connections active
    // Do not cancel any conversation requests, let them continue running in the background

    // Record current running conversation
    if (streamingConversations.size > 0) {
      // Keep existing SSE connections active
    }

    // Reset all states
    setInput("");
    setIsLoading(false);
    setIsSwitchedConversation(false);

    // Use conversation management hook
    conversationManagement.handleNewConversation();
    setIsLoadingHistoricalConversation(false); // Ensure not loading historical conversation

    // Reset streaming state
    setIsStreaming(false);

    // Reset selected message and right panel state
    setSelectedMessageId(undefined);
    setShowRightPanel(false);

    // Reset attachment state
    setAttachments([]);
    setFileUrls({});

    // Clear URL parameters
    const url = new URL(window.location.href);
    if (url.searchParams.has("q")) {
      url.searchParams.delete("q");
      window.history.replaceState({}, "", url.toString());
    }

    // Wait for all state updates to complete
    await new Promise((resolve) => setTimeout(resolve, 0));

    // Ensure new conversation scrolls to bottom
    setShouldScrollToBottom(true);
  };


  // When switching conversation, automatically load messages
  const handleDialogClick = async (dialog: ConversationListItem) => {
    // When switching conversation, keep all SSE connections active
    // Do not cancel any conversation requests, let them continue running in the background

    // Use conversation management hook
    conversationManagement.handleConversationSelect(dialog);
    setSelectedMessageId(undefined);
    setShowRightPanel(false);

    // When user views conversation, clear completed state
    setCompletedConversations((prev) => {
      const newSet = new Set(prev);
      newSet.delete(dialog.conversation_id);
      return newSet;
    });

    // Check if there are cached messages
    const hasCachedMessages =
      sessionMessages[dialog.conversation_id] !== undefined;
    const isCurrentActive = dialog.conversation_id === conversationManagement.conversationId;

    // Log: click conversation
    // If there are cached messages, ensure not to show loading state
    if (hasCachedMessages) {
      const cachedMessages = sessionMessages[dialog.conversation_id];
      // If cache is empty array, force reload historical messages
      if (cachedMessages && cachedMessages.length === 0) {
        setIsLoadingHistoricalConversation(true);
        setIsLoading(true);

        try {
          // Create new AbortController for current request
          const controller = new AbortController();

          // Set timeout timer - 120 seconds
          timeoutRef.current = setTimeout(() => {
            if (controller && !controller.signal.aborted) {
              try {
                controller.abort(t("chatInterface.requestTimeout"));
              } catch (error) {
                log.error(t("chatInterface.errorCancelingRequest"), error);
              }
            }
            timeoutRef.current = null;
          }, 120000);

          // Save current controller reference
          abortControllerRef.current = controller;

          // Use controller.signal to make request with timeout
          const data = await conversationService.getDetail(
            dialog.conversation_id,
            controller.signal
          );

          // Clear timeout timer after request completes
          if (timeoutRef.current) {
            clearTimeout(timeoutRef.current);
            timeoutRef.current = null;
          }

          // Don't process result if request was canceled
          if (controller.signal.aborted) {
            return;
          }

          if (data.code === 0 && data.data && data.data.length > 0) {
            const conversationData = data.data[0] as ApiConversationDetail;
            const dialogMessages = conversationData.message || [];

            // Immediately process messages, do not use setTimeout
            const formattedMessages: ChatMessageType[] = [];

            // Optimized processing logic: process messages by role one by one, maintain original order
            dialogMessages.forEach((dialog_msg, index) => {
              if (dialog_msg.role === MESSAGE_ROLES.USER) {
                const formattedUserMsg: ChatMessageType =
                  extractUserMsgFromResponse(
                    dialog_msg,
                    index,
                    conversationData.create_time
                  );
                formattedMessages.push(formattedUserMsg);
              } else if (dialog_msg.role === MESSAGE_ROLES.ASSISTANT) {
                const formattedAssistantMsg: ChatMessageType =
                  extractAssistantMsgFromResponse(
                    dialog_msg,
                    index,
                    conversationData.create_time,
                    t
                  );
                formattedMessages.push(formattedAssistantMsg);
              }
            });

            // Update message array
            setSessionMessages((prev) => ({
              ...prev,
              [dialog.conversation_id]: formattedMessages,
            }));

            // Clear any previous error for this conversation
            conversationManagement.clearConversationLoadError(dialog.conversation_id);

            // Asynchronously load all attachment URLs
            loadAttachmentUrls(formattedMessages, dialog.conversation_id);

            // Trigger scroll to bottom
            setShouldScrollToBottom(true);

            // Reset shouldScrollToBottom after a delay to ensure scrolling completes.
            setTimeout(() => {
              setShouldScrollToBottom(false);
            }, 1000);

            // Note: Removed unnecessary conversation list refresh when loading historical messages
            // Only refresh when creating, deleting, or renaming conversations
          } else {
            // No longer empty cache, only prompt no history messages
            conversationManagement.setConversationLoadErrorForId(
              dialog.conversation_id,
              t("chatStreamMain.noHistory") || "该会话无历史消息"
            );
          }
        } catch (error) {
          log.error(
            t("chatInterface.errorFetchingConversationDetailsError"),
            error
          );
          // if error, don't set empty array, keep existing state to avoid showing new conversation interface
          // Instead, we can show an error message or retry mechanism

          conversationManagement.setConversationLoadErrorForId(dialog.conversation_id, "Failed to load conversation");
        } finally {
          // ensure loading state is cleared
          setIsLoading(false);
          setIsLoadingHistoricalConversation(false);
        }
      } else {
        // Cache has content, display normally
        setIsLoadingHistoricalConversation(false);
        setIsLoading(false); // Ensure isLoading state is also reset

        // For cases where there are cached messages, also trigger scrolling to the bottom.
        setShouldScrollToBottom(true);
        setTimeout(() => {
          setShouldScrollToBottom(false);
        }, 1000);
      }
    }

    // If there are no cached messages and not current active conversation, load historical messages
    if (!hasCachedMessages && !isCurrentActive) {
      // Set loading historical conversation state
      setIsLoadingHistoricalConversation(true);
      setIsLoading(true);

      try {
        // Create new AbortController for current request
        const controller = new AbortController();

        // Set timeout timer - 120 seconds
        timeoutRef.current = setTimeout(() => {
          if (controller && !controller.signal.aborted) {
            try {
              controller.abort(t("chatInterface.requestTimeout"));
            } catch (error) {
              log.error(t("chatInterface.errorCancelingRequest"), error);
            }
          }
          timeoutRef.current = null;
        }, 120000);

        // Save current controller reference
        abortControllerRef.current = controller;

        // Use controller.signal to make request with timeout
        const data = await conversationService.getDetail(
          dialog.conversation_id,
          controller.signal
        );

        // Clear timeout timer after request completes
        if (timeoutRef.current) {
          clearTimeout(timeoutRef.current);
          timeoutRef.current = null;
        }

        // Don't process result if request was canceled
        if (controller.signal.aborted) {
          return;
        }

        if (data.code === 0 && data.data && data.data.length > 0) {
          const conversationData = data.data[0] as ApiConversationDetail;
          const dialogMessages = conversationData.message || [];

          // Immediately process messages, do not use setTimeout
          const formattedMessages: ChatMessageType[] = [];

          // Optimized processing logic: process messages by role one by one, maintain original order
          dialogMessages.forEach((dialog_msg, index) => {
            if (dialog_msg.role === MESSAGE_ROLES.USER) {
              const formattedUserMsg: ChatMessageType =
                extractUserMsgFromResponse(
                  dialog_msg,
                  index,
                  conversationData.create_time
                );
              formattedMessages.push(formattedUserMsg);
            } else if (dialog_msg.role === ROLE_ASSISTANT) {
              const formattedAssistantMsg: ChatMessageType =
                extractAssistantMsgFromResponse(
                  dialog_msg,
                  index,
                  conversationData.create_time,
                  t
                );
              formattedMessages.push(formattedAssistantMsg);
            }
          });

          // Update message array
          setSessionMessages((prev) => ({
            ...prev,
            [dialog.conversation_id]: formattedMessages,
          }));

          // Clear any previous error for this conversation
          conversationManagement.clearConversationLoadError(dialog.conversation_id);

          // Asynchronously load all attachment URLs
          loadAttachmentUrls(formattedMessages, dialog.conversation_id);

          // Trigger scroll to bottom
          setShouldScrollToBottom(true);

          // Reset shouldScrollToBottom after a delay to ensure scrolling completes.
          setTimeout(() => {
            setShouldScrollToBottom(false);
          }, 1000);

          // Note: Removed unnecessary conversation list refresh when loading historical messages
          // Only refresh when creating, deleting, or renaming conversations
        } else {
          // No longer empty cache, only prompt no history messages
          conversationManagement.setConversationLoadErrorForId(
            dialog.conversation_id,
            t("chatStreamMain.noHistory") || "该会话无历史消息"
          );
        }
      } catch (error) {
        log.error(
          t("chatInterface.errorFetchingConversationDetailsError"),
          error
        );
        // if error, don't set empty array, keep existing state to avoid showing new conversation interface
        // Instead, we can show an error message or retry mechanism

        conversationManagement.setConversationLoadErrorForId(dialog.conversation_id, "Failed to load conversation");
      } finally {
        // ensure loading state is cleared
        setIsLoading(false);
        setIsLoadingHistoricalConversation(false);
      }
    }
  };

  // Add function to asynchronously load attachment URLs
  const loadAttachmentUrls = async (
    messages: ChatMessageType[],
    targetConversationId?: number
  ) => {
    // Create a copy to avoid directly modifying parameters
    const updatedMessages = [...messages];
    let hasUpdates = false;
    const conversationIdToUse = targetConversationId || conversationManagement.conversationId;

    // Process attachments for each message
    for (const message of updatedMessages) {
      if (message.attachments && message.attachments.length > 0) {
        // Get URL for each attachment
        for (const attachment of message.attachments) {
          if (attachment.object_name && !attachment.url) {
            try {
              // Get file URL
              const url = await storageService.getFileUrl(
                attachment.object_name
              );
              // Update attachment info
              attachment.url = url;
              hasUpdates = true;
            } catch (error) {
              log.error(
                t("chatInterface.errorFetchingAttachmentUrl", {
                  object_name: attachment.object_name,
                }),
                error
              );
            }
          }
        }
      }
    }

    // If there are updates, set new message array
    if (hasUpdates) {
      setSessionMessages((prev) => ({
        ...prev,
        [conversationIdToUse]: updatedMessages,
      }));
    }
  };

  // Left sidebar conversation title update
  const handleConversationRename = async (dialogId: number, title: string) => {
    try {
      await conversationService.rename(dialogId, title);
      await conversationManagement.fetchConversationList();

      if (conversationManagement.selectedConversationId === dialogId) {
        conversationManagement.setConversationTitle(title);
      }
    } catch (error) {
      log.error(t("chatInterface.renameFailed"), error);
    }
  };

  // Left sidebar conversation deletion
  const handleConversationDeleteClick = async (dialogId: number) => {
    try {
      // If deleting the currently active conversation, stop conversation first
      if (
        conversationManagement.selectedConversationId === dialogId &&
        isStreaming &&
        conversationManagement.conversationId === dialogId
      ) {
        // Cancel current ongoing request first
        if (abortControllerRef.current) {
          try {
            abortControllerRef.current.abort(
              t("chatInterface.deleteConversation")
            );
          } catch (error) {
            log.error(t("chatInterface.errorCancelingRequest"), error);
          }
          abortControllerRef.current = null;
        }

        // Clear timeout timer
        if (timeoutRef.current) {
          clearTimeout(timeoutRef.current);
          timeoutRef.current = null;
        }

        setIsStreaming(false);
        setIsLoading(false);

        try {
          await conversationService.stop(dialogId);
        } catch (error) {
          log.error(
            t("chatInterface.stopConversationToDeleteFailed"),
            error
          );
          // Continue deleting even if stopping fails
        }
      }

      await conversationService.delete(dialogId);
      await conversationManagement.fetchConversationList();

      if (conversationManagement.selectedConversationId === dialogId) {
        conversationManagement.setSelectedConversationId(null);
        // Update ref to track current selected conversation
        conversationManagement.currentSelectedConversationRef.current = null;
        conversationManagement.setConversationTitle(t("chatInterface.newConversation"));
        handleNewConversation();
      }
    } catch (error) {
      log.error(t("chatInterface.deleteFailed"), error);
    }
  };

  // Add image error handling function
  const handleImageError = (imageUrl: string) => {
    log.error(t("chatInterface.imageLoadFailed"), imageUrl);

    // Remove failed images from messages
    setSessionMessages((prev) => {
      const newMessages = { ...prev };
      const lastMsg =
        newMessages[conversationManagement.conversationId]?.[newMessages[conversationManagement.conversationId].length - 1];

      if (lastMsg && lastMsg.role === ROLE_ASSISTANT && lastMsg.images) {
        // Filter out failed images
        lastMsg.images = lastMsg.images.filter((url) => url !== imageUrl);
      }

      return newMessages;
    });
  };

  // Handle image click preview
  const handleImageClick = (imageUrl: string) => {
    setViewingImage(imageUrl);
  };

  // Add conversation stop handling function
  const handleStop = async () => {
    // Stop agent_run of current conversation
    const currentController =
      conversationControllersRef.current.get(conversationManagement.conversationId);
    if (currentController) {
      try {
        currentController.abort(t("chatInterface.userManuallyStopped"));
      } catch (error) {
        log.error(t("chatInterface.errorCancelingRequest"), error);
      }
      conversationControllersRef.current.delete(conversationManagement.conversationId);
    }

    // Clear timeout timer for current conversation
    const currentTimeout = conversationTimeoutsRef.current.get(conversationManagement.conversationId);
    if (currentTimeout) {
      clearTimeout(currentTimeout);
      conversationTimeoutsRef.current.delete(conversationManagement.conversationId);
    }

    // Immediately update frontend state
    setIsStreaming(false);
    setIsLoading(false);

    // If no valid conversation ID, just reset frontend state
    if (!conversationManagement.conversationId || conversationManagement.conversationId === -1) {
      return;
    }

    try {
      // Call backend stop API - this will stop both agent run and preprocess tasks
      await conversationService.stop(conversationManagement.conversationId);

      // Manually update messages, clear thinking state
      setSessionMessages((prev) => {
        const newMessages = { ...prev };
        const lastMsg =
          newMessages[conversationManagement.conversationId]?.[newMessages[conversationManagement.conversationId].length - 1];
        if (lastMsg && lastMsg.role === ROLE_ASSISTANT) {
          lastMsg.isComplete = true;
          lastMsg.thinking = undefined; // Explicitly clear thinking state
        }
        return newMessages;
      });

      // remove from streaming list
      setStreamingConversations((prev) => {
        const newSet = new Set(prev);
        newSet.delete(conversationManagement.conversationId);
        return newSet;
      });

      // when conversation is stopped, only add to completed conversations list when user is not in current conversation interface
      const currentUserConversation = currentSelectedConversationRef.current;
      if (currentUserConversation !== conversationManagement.conversationId) {
        setCompletedConversations((prev) => {
          const newSet = new Set(prev);
          newSet.add(conversationManagement.conversationId);
          return newSet;
        });
      }
    } catch (error) {
      log.error(t("chatInterface.stopConversationFailed"), error);

      // Optionally show error message
      setSessionMessages((prev) => {
        const newMessages = { ...prev };
        const lastMsg =
          newMessages[conversationManagement.conversationId]?.[newMessages[conversationManagement.conversationId].length - 1];
        if (lastMsg && lastMsg.role === ROLE_ASSISTANT) {
          lastMsg.isComplete = true;
          lastMsg.thinking = undefined; // Explicitly clear thinking state
          lastMsg.error = t(
            "chatInterface.stopConversationFailedButFrontendStopped"
          );
        }
        return newMessages;
      });
    }
  };

  // Top title rename function
  const handleTitleRename = async (newTitle: string) => {
    if (conversationManagement.selectedConversationId && newTitle !== conversationManagement.conversationTitle) {
      try {
        await conversationManagement.updateConversationTitle(conversationManagement.selectedConversationId, newTitle);
      } catch (error) {
        log.error(t("chatInterface.renameFailed"), error);
      }
    }
  };

  // Handle message selection
  const handleMessageSelect = (messageId: string) => {
    if (messageId !== selectedMessageId) {
      // If clicking on new message, set as selected and open right panel
      setSelectedMessageId(messageId);
      // Auto open right panel
      setShowRightPanel(true);
    } else {
      // If clicking on already selected message, toggle panel state
      toggleRightPanel();
    }
  };

  // Like/dislike handling
  const handleOpinionChange = async (
    messageId: number,
    opinion: "Y" | "N" | null
  ) => {
    try {
      await conversationService.updateOpinion({
        message_id: messageId,
        opinion,
      });
      setSessionMessages((prev) => {
        const newMessages = { ...prev };
        // Update the opinion_flag for the specific message in all conversations
        Object.keys(newMessages).forEach((conversationId) => {
          const messages = newMessages[parseInt(conversationId)];
          if (messages) {
            const messageIndex = messages.findIndex(
              (msg) => msg.message_id === messageId
            );
            if (messageIndex !== -1) {
              newMessages[parseInt(conversationId)] = [...messages];
              newMessages[parseInt(conversationId)][messageIndex] = {
                ...newMessages[parseInt(conversationId)][messageIndex],
                opinion_flag: opinion || undefined,
              };
            }
          }
        });
        return newMessages;
      });
    } catch (error) {
      log.error(t("chatInterface.updateOpinionFailed"), error);
    }
  };

  // Add event listener for conversation list updates
  useEffect(() => {
    const handleConversationListUpdate = () => {
      conversationManagement.fetchConversationList().catch((err) => {
        log.error(t("chatInterface.failedToUpdateConversationList"), err);
      });
    };

    window.addEventListener(
      "conversationListUpdated",
      handleConversationListUpdate
    );

    return () => {
      window.removeEventListener(
        "conversationListUpdated",
        handleConversationListUpdate
      );
    };
  }, []);

  // Handle settings click - not used when menu items are provided
  const handleSettingsClick = () => {
    // This function is kept for compatibility but not used
    // Both admin and regular users now use dropdown menus
  };



  return (
    <>
      <div className="flex h-full">
        <ChatSidebar
          conversationList={conversationManagement.conversationList}
          selectedConversationId={conversationManagement.selectedConversationId}
          openDropdownId={openDropdownId}
          streamingConversations={streamingConversations}
          completedConversations={completedConversations}
          onNewConversation={handleNewConversation}
          onDialogClick={handleDialogClick}
          onRename={handleConversationRename}
          onDelete={handleConversationDeleteClick}
          onSettingsClick={handleSettingsClick}
          onDropdownOpenChange={(open: boolean, id: string | null) =>
            setOpenDropdownId(open ? id : null)
          }
          onToggleSidebar={toggleSidebar}
          expanded={sidebarOpen}
          userEmail={user?.email}
          userAvatarUrl={user?.avatarUrl}
          userRole={user?.role}
        />

        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex flex-1 overflow-hidden">
            <div className="flex-1 flex flex-col">
              <ChatHeader
                title={conversationManagement.conversationTitle}
                onRename={handleTitleRename}
              />

              <ChatStreamMain
                messages={currentMessages}
                input={input}
                isLoading={isLoading}
                isStreaming={isCurrentConversationStreaming}
                isLoadingHistoricalConversation={
                  isLoadingHistoricalConversation
                }
                conversationLoadError={
                  conversationManagement.conversationLoadError[conversationManagement.selectedConversationId || 0]
                }
                onInputChange={(value: string) => setInput(value)}
                onSend={handleSend}
                onStop={handleStop}
                onKeyDown={handleKeyDown}
                onSelectMessage={handleMessageSelect}
                selectedMessageId={selectedMessageId}
                attachments={attachments}
                onAttachmentsChange={handleAttachmentsChange}
                onFileUpload={handleFileUpload}
                onImageUpload={handleImageUpload}
                onOpinionChange={handleOpinionChange}
                currentConversationId={conversationManagement.conversationId}
                shouldScrollToBottom={shouldScrollToBottom}
                selectedAgentId={selectedAgentId}
                onAgentSelect={setSelectedAgentId}
                onCitationHover={clearCompletedIndicator}
                onScroll={clearCompletedIndicator}
              />
            </div>

            <ChatRightPanel
              messages={currentMessages}
              onImageError={handleImageError}
              maxInitialImages={14}
              isVisible={showRightPanel}
              toggleRightPanel={toggleRightPanel}
              selectedMessageId={selectedMessageId}
            />
          </div>
        </div>
      </div>
      <TooltipProvider>
        <Tooltip
          title={t("chatInterface.stopGenerating")}
          open={false}
          placement="top"
        >
          <div className="fixed inset-0 pointer-events-none" />
        </Tooltip>
      </TooltipProvider>
    </>
  );
}
