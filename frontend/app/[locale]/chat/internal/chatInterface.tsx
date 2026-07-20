"use client";

import type React from "react";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { v4 as uuidv4 } from "uuid";
import { useTranslation } from "react-i18next";

import { ROLE_ASSISTANT } from "@/const/agentConfig";
import { MESSAGE_ROLES } from "@/const/chatConfig";
import { useConfig } from "@/hooks/useConfig";
import { useModelList } from "@/hooks/model/useModelList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { conversationService } from "@/services/conversationService";
import {
  analyzeAutomationMessage,
  canAnalyzeAutomationMessage,
  createPreparingAutomationMessage,
  getAutomationConversationIds,
  hydrateAutomationProposalMessages,
  resolveAutomationProposalMessage,
  resolvePreparingMessageAsAgentReply,
} from "@/features/agentAutomation/chatAdapter";
import { getAutomationErrorMessage } from "@/features/agentAutomation/errorMessage";
import {
  storageService,
  convertImageUrlToApiUrl,
} from "@/services/storageService";
import { useConversationManagement } from "@/hooks/chat/useConversationManagement";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";

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
} from "@/lib/chat/chatAttachmentUtils";
import {
  ConversationListItem,
  ApiConversationDetail,
  HistoryItem,
} from "@/types/chat";
import type { Agent } from "@/types/agentConfig";
import { ChatMessageType } from "@/types/chat";
import {
  handleStreamResponse,
  ResumeConfig,
  StreamingMessage,
} from "@/app/chat/streaming/chatStreamHandler";
import { formatConversationMessagesFromResponse } from "@/lib/chatMessageExtractor";

import { Button, Checkbox, Input, Layout, message, Modal } from "antd";
import log from "@/lib/logger";

const stepIdCounter = { current: 0 };

let cachedShareBaseUrl: string | null | undefined;

const getConfiguredShareBaseUrl = async () => {
  if (cachedShareBaseUrl !== undefined) return cachedShareBaseUrl;

  const buildTimeBaseUrl = process.env.NEXT_PUBLIC_SHARE_BASE_URL?.trim();
  if (buildTimeBaseUrl) {
    cachedShareBaseUrl = buildTimeBaseUrl;
    return cachedShareBaseUrl;
  }

  try {
    const response = await fetch("/api/frontend-config", { cache: "no-store" });
    if (response.ok) {
      const data = await response.json();
      const runtimeBaseUrl = data.shareBaseUrl?.trim();
      cachedShareBaseUrl = runtimeBaseUrl || null;
      return cachedShareBaseUrl;
    }
  } catch (error) {
    log.warn("Failed to load runtime frontend config", error);
  }

  cachedShareBaseUrl = null;
  return cachedShareBaseUrl;
};

const buildShareUrl = async (shareId: string, locale: string) => {
  const configuredBaseUrl = await getConfiguredShareBaseUrl();
  const baseUrl = configuredBaseUrl || window.location.origin;
  return `${baseUrl.replace(/\/+$/, "")}/${locale}/share/${shareId}`;
};

const copyTextToClipboard = async (text: string): Promise<boolean> => {
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (error) {
      log.warn("Clipboard API failed, falling back to textarea copy", error);
    }
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "0";
  textarea.style.left = "0";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();

  try {
    return document.execCommand("copy");
  } catch (error) {
    log.warn("Textarea copy fallback failed", error);
    return false;
  } finally {
    document.body.removeChild(textarea);
  }
};

// Get internationalization key based on message type
const getI18nKeyByType = (type: string): string => {
  const typeToKeyMap: Record<string, string> = {
    progress: "chatInterface.parsingFileWithProgress",
    truncation: "chatInterface.fileTruncated",
  };
  return typeToKeyMap[type] || "";
};

export function ChatInterface() {
  const [input, setInput] = useState("");
  // Replace the original messages state
  const [sessionMessages, setSessionMessages] = useState<{
    [conversationId: number]: ChatMessageType[];
  }>({});
  const sessionMessagesRef = useRef<{
    [conversationId: number]: ChatMessageType[];
  }>({});
  const [isSwitchedConversation, setIsSwitchedConversation] = useState(false); // Add conversation switching tracking state
  const [isLoading, setIsLoading] = useState(false);
  const { t, i18n } = useTranslation("common");

  // Use conversation management hook
  const conversationManagement = useConversationManagement();
  const linkedConversationHandledRef = useRef(false);
  const handleDialogClickRef = useRef<
    (dialog: ConversationListItem) => Promise<void>
  >(async () => undefined);

  // Use model list hook for model selection
  const { models: availableModels } = useModelList();

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
  // If a historical conversation is being loaded and there are no cached messages, return an empty array to avoid displaying error content.
  // For pending new conversations (placeholder key -1), show messages even though no
  // real conversation_id has been returned yet from the backend.
  const currentMessages = conversationManagement.selectedConversationId
    ? sessionMessages[conversationManagement.selectedConversationId] || []
    : sessionMessages[-1] || [];

  // Monitor changes in currentMessages
  // Calculate if the current conversation is streaming
  const isCurrentConversationStreaming =
    conversationManagement.selectedConversationId != null
      ? streamingConversations.has(
          conversationManagement.selectedConversationId
        )
      : streamingConversations.has(-1);

  const [viewingImage, setViewingImage] = useState<string | null>(null);

  // Add attachment state management
  const [attachments, setAttachments] = useState<FilePreview[]>([]);
  const [fileUrls, setFileUrls] = useState<{ [id: string]: string }>({});

  const [isStreaming, setIsStreaming] = useState(false); // Add streaming state
  const abortControllerRef = useRef<AbortController | null>(null); // Add AbortController reference
  const timeoutRef = useRef<NodeJS.Timeout | null>(null); // Add timeout reference

  // Add a state to track if we're loading a historical conversation
  const [isLoadingHistoricalConversation, setIsLoadingHistoricalConversation] =
    useState(false);

  // Add a state to track completed conversations that haven't been viewed yet
  const [completedConversations, setCompletedConversations] = useState<
    Set<number>
  >(new Set());
  const [automationConversationIds, setAutomationConversationIds] = useState<
    Set<number>
  >(new Set());

  // Ensure right sidebar is closed by default
  const [showRightPanel, setShowRightPanel] = useState(false);

  const [selectedMessageId, setSelectedMessageId] = useState<
    string | undefined
  >();

  // Add force scroll to bottom state control
  const [shouldScrollToBottom, setShouldScrollToBottom] = useState(false);

  // Add agent selection state
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [agentGreeting, setAgentGreeting] = useState<string | null>(null);
  const [agentExampleQuestions, setAgentExampleQuestions] = useState<string[]>(
    []
  );
  const [isShareMode, setIsShareMode] = useState(false);
  const [selectedShareMessageIds, setSelectedShareMessageIds] = useState<
    Set<number>
  >(new Set());
  const [isCreatingShare, setIsCreatingShare] = useState(false);
  const [manualShareUrl, setManualShareUrl] = useState<string | null>(null);
  const [agentModelIds, setAgentModelIds] = useState<number[]>([]);
  const [agentModelNames, setAgentModelNames] = useState<string[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<number | null>(null);
  const { agents: publishedAgents = [] } = usePublishedAgentList() as {
    agents: Agent[];
  };

  const loadAutomationConversationIds = useCallback(async () => {
    try {
      setAutomationConversationIds(await getAutomationConversationIds());
    } catch (error) {
      log.warn("Failed to load automation task markers", error);
    }
  }, []);

  useEffect(() => {
    void loadAutomationConversationIds();
    window.addEventListener(
      "automationListUpdated",
      loadAutomationConversationIds
    );
    return () => {
      window.removeEventListener(
        "automationListUpdated",
        loadAutomationConversationIds
      );
    };
  }, [loadAutomationConversationIds]);

  useEffect(() => {
    sessionMessagesRef.current = sessionMessages;
  }, [sessionMessages]);

  const handleAgentSelectWithGreeting = useCallback(
    (
      agentId: string | null,
      greeting?: string,
      exampleQuestions?: string[],
      modelIds?: number[],
      modelNames?: string[]
    ) => {
      setSelectedAgentId(agentId);
      setAgentGreeting(greeting || null);
      setAgentExampleQuestions(exampleQuestions || []);
      setAgentModelIds(modelIds || []);
      setAgentModelNames(modelNames || []);
      setSelectedModelId(modelIds && modelIds.length > 0 ? modelIds[0] : null);
    },
    []
  );

  const restoreConversationAgent = useCallback(
    (agentId?: number | string | null) => {
      if (agentId === undefined || agentId === null) {
        handleAgentSelectWithGreeting(null);
        return;
      }

      const normalizedAgentId = String(agentId);
      const agent = publishedAgents.find(
        (item) => item.id === normalizedAgentId
      );

      if (!agent && publishedAgents.length === 0) {
        setSelectedAgentId(normalizedAgentId);
        setAgentGreeting(null);
        setAgentExampleQuestions([]);
        setAgentModelIds([]);
        setAgentModelNames([]);
        setSelectedModelId(null);
        return;
      }

      if (!agent || agent.is_available === false) {
        handleAgentSelectWithGreeting(null);
        return;
      }

      handleAgentSelectWithGreeting(
        normalizedAgentId,
        agent.greeting_message,
        agent.example_questions,
        agent.model_ids,
        agent.model_names
      );
    },
    [handleAgentSelectWithGreeting, publishedAgents]
  );

  useEffect(() => {
    if (!selectedAgentId || publishedAgents.length === 0) {
      return;
    }

    const agent = publishedAgents.find((item) => item.id === selectedAgentId);
    if (!agent || agent.is_available === false) {
      handleAgentSelectWithGreeting(null);
      return;
    }

    setAgentGreeting(agent.greeting_message || null);
    setAgentExampleQuestions(agent.example_questions || []);
    setAgentModelIds(agent.model_ids || []);
    setAgentModelNames(agent.model_names || []);
    setSelectedModelId(
      agent.model_ids && agent.model_ids.length > 0 ? agent.model_ids[0] : null
    );
  }, [handleAgentSelectWithGreeting, publishedAgents, selectedAgentId]);

  useEffect(() => {
    const agentId = sessionStorage.getItem("selectedAgentId");
    // Set selected agent ID from sessionStorage if it exists
    if (agentId) {
      setSelectedAgentId(agentId);
      sessionStorage.removeItem("selectedAgentId");
    }
  }, []);

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

  // Handle right panel toggle - keep it simple and clear
  const toggleRightPanel = () => {
    setShowRightPanel(!showRightPanel);
  };

  // Add useEffect to listen for conversationId changes, ensure right sidebar is always closed when conversation switches
  useEffect(() => {
    // Ensure right sidebar is reset to closed state whenever conversation ID changes
    setSelectedMessageId(undefined);
    setShowRightPanel(false);
  }, [conversationManagement.selectedConversationId]);

  // Helper function to clear completed conversation indicator
  const clearCompletedIndicator = useCallback(() => {
    if (conversationManagement.selectedConversationId != null) {
      setCompletedConversations((prev) => {
        // Use functional update to avoid dependency on completedConversations
        if (
          conversationManagement.selectedConversationId != null &&
          prev.has(conversationManagement.selectedConversationId)
        ) {
          const newSet = new Set(prev);
          newSet.delete(conversationManagement.selectedConversationId);
          return newSet;
        }
        return prev;
      });
    }
  }, [conversationManagement.selectedConversationId]);

  // Add useEffect to clear completed conversation indicator when user is viewing the current conversation
  useEffect(() => {
    // If current conversation is in completedConversations, clear it when user is viewing it
    clearCompletedIndicator();
  }, [conversationManagement.selectedConversationId, clearCompletedIndicator]);

  // Add click event listener to clear completed conversation indicator when user clicks anywhere on the page
  useEffect(() => {
    const handlePageClick = (e: MouseEvent) => {
      // Clear completed indicator when user clicks anywhere on the page
      clearCompletedIndicator();
    };

    // Add click event listener to the document
    document.addEventListener("click", handlePageClick, true);

    return () => {
      document.removeEventListener("click", handlePageClick, true);
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
    const shouldResetButtonStates = true;

    // Ensure right sidebar doesn't auto-expand when sending new message
    setSelectedMessageId(undefined);
    setShowRightPanel(false);

    // Handle user message content
    const userMessageId = uuidv4();
    const userMessageContent = input.trim();

    // Get current conversation ID (null when new conversation)
    const currentConversationId = conversationManagement.selectedConversationId;
    const selectedAgentIdForRun = selectedAgentId;
    const agentIdForRun =
      selectedAgentIdForRun !== null ? Number(selectedAgentIdForRun) : null;
    let cid: number | null = null; // set after guard, used in try/catch/finally

    // Prepare attachment information
    // Handle file upload
    let uploadedFileUrls: Record<string, string> = {};
    let objectNames: Record<string, string> = {}; // Add object name mapping
    let presignedUrls: Record<string, string> = {}; // Store presigned URLs for external MCP tool access

    if (attachments.length > 0) {
      // Show loading state
      setIsLoading(true);

      // Use preprocessing function to upload attachments
      const uploadResult = await uploadAttachments(attachments, t);
      if (uploadResult.error) {
        message.error(
          `${t("chatPreprocess.fileUploadFailed")} ${uploadResult.error}`
        );
        setIsLoading(false);
        return;
      }
      uploadedFileUrls = uploadResult.uploadedFileUrls;
      objectNames = uploadResult.objectNames; // Get object name mapping
      presignedUrls = uploadResult.presignedUrls; // Get presigned URLs for external access

      const missingUploads = attachments.filter(
        (attachment) =>
          !uploadedFileUrls[attachment.file.name] ||
          !objectNames[attachment.file.name]
      );
      if (missingUploads.length > 0) {
        message.error(
          `${t("chatPreprocess.fileUploadFailed")} ${missingUploads.map((item) => item.file.name).join(", ")}`
        );
        setIsLoading(false);
        return;
      }
    }

    // Use preprocessing function to create message attachments
    const messageAttachments = createMessageAttachments(
      attachments,
      uploadedFileUrls,
      fileUrls,
      objectNames,
      presignedUrls
    );

    // Create user message object
    const userMessage: ChatMessageType = {
      id: userMessageId,
      role: MESSAGE_ROLES.USER,
      content: userMessageContent,
      timestamp: new Date(),
      isComplete: true,
      steps: [],
      attachments:
        messageAttachments.length > 0 ? messageAttachments : undefined,
      images: [],
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
    const shouldAnalyzeAutomation = canAnalyzeAutomationMessage(
      attachments.length,
      agentIdForRun,
      userMessageContent
    );
    const preparingAutomationMessage = shouldAnalyzeAutomation
      ? createPreparingAutomationMessage(
          assistantMessageId,
          initialAssistantMessage.timestamp
        )
      : null;

    // Send message and scroll to bottom
    setShouldScrollToBottom(true);

    setIsLoading(true);
    setIsStreaming(true); // Set streaming state to true

    // Create independent AbortController for current conversation
    const currentController = new AbortController();

    // Render the user message before automation intent analysis or the normal
    // Agent request starts. New conversations use the existing placeholder and
    // migrate to the backend-created conversation ID later.
    const placeholderId = -1;
    const id = currentConversationId ?? placeholderId;
    cid = id;
    setSessionMessages((prev) => ({
      ...prev,
      [id]: [
        ...(prev[id] || []),
        userMessage,
        ...(preparingAutomationMessage ? [preparingAutomationMessage] : []),
      ],
    }));

    try {
      // Handle scheduled requests as chat commands before a normal Agent run.
      // This prevents a recurring command from executing once immediately.
      if (shouldAnalyzeAutomation) {
        try {
          const proposal = await analyzeAutomationMessage({
            conversationId: currentConversationId ?? undefined,
            agentId: agentIdForRun,
            message: userMessageContent,
            modelId: selectedModelId,
          });
          if (proposal?.proposal_id && proposal.task) {
            const proposalConversationId =
              proposal.conversation_id ?? currentConversationId;
            if (!proposalConversationId) {
              throw new Error("Automation proposal is missing conversation_id");
            }
            cid = proposalConversationId;
            setSessionMessages((prev) => {
              const optimisticMessages = prev[id] || [];
              const proposalMessages =
                proposalConversationId === id
                  ? optimisticMessages
                  : [
                      ...(prev[proposalConversationId] || []),
                      ...optimisticMessages,
                    ];
              const nextMessages = resolveAutomationProposalMessage(
                proposalMessages,
                assistantMessageId,
                proposal
              );
              const nextState = {
                ...prev,
                [proposalConversationId]: nextMessages,
              };
              if (proposalConversationId !== id) {
                delete nextState[id];
              }
              return nextState;
            });
            conversationManagement.setSelectedConversationId(
              proposalConversationId
            );
            const conversationTitle =
              proposal.task.title || t("chatInterface.newConversation");
            conversationManagement.setConversationTitle(conversationTitle);
            if (currentConversationId == null) {
              conversationManagement.prependConversation(
                proposalConversationId,
                conversationTitle,
                agentIdForRun
              );
            } else {
              conversationManagement.updateConversationAgentId(
                proposalConversationId,
                agentIdForRun
              );
            }
            setShouldScrollToBottom(true);
            return;
          }
        } catch (error) {
          log.warn("Failed to handle automation chat command", error);
          const errorMessage = getAutomationErrorMessage(
            error,
            t,
            "agentAutomation.proposal.createFailed"
          );
          message.error(errorMessage);
          setSessionMessages((prev) => {
            const existingMessages = prev[id] || [];
            const nextMessages = existingMessages.filter(
              (item) =>
                item.id !== userMessageId && item.id !== assistantMessageId
            );
            if (nextMessages.length === existingMessages.length) return prev;
            const nextState = { ...prev };
            if (nextMessages.length > 0) {
              nextState[id] = nextMessages;
            } else {
              delete nextState[id];
            }
            return nextState;
          });
          setInput(userMessageContent);
          return;
        }
      }

      // Register controller and streaming state for this conversation
      conversationControllersRef.current.set(id, currentController);
      setStreamingConversations((prev) => {
        const newSet = new Set(prev);
        newSet.add(id);
        return newSet;
      });

      // Reuse the automation-analysis placeholder for a normal Agent reply, so
      // chat only swaps message state and does not own automation UI details.
      setSessionMessages((prev) => {
        const assistantMessage = {
          ...initialAssistantMessage,
          id: initialAssistantMessage.id || uuidv4(),
          timestamp: initialAssistantMessage.timestamp || new Date(),
          isComplete: initialAssistantMessage.isComplete ?? false,
          steps: initialAssistantMessage.steps || [],
          attachments: initialAssistantMessage.attachments || [],
          images: initialAssistantMessage.images || [],
        };
        return {
          ...prev,
          [id]: shouldAnalyzeAutomation
            ? resolvePreparingMessageAsAgentReply(
                prev[id] || [],
                assistantMessageId,
                assistantMessage
              )
            : [...(prev[id] || []), assistantMessage],
        };
      });

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
          currentConversationId ?? undefined
        );

        finalQuery = result.finalQuery;
        fileDescriptionsMap = result.fileDescriptions || {};
      }

      // Send request to backend API, add signal parameter
      const runAgentParams: Parameters<typeof conversationService.runAgent>[0] =
        {
          query: finalQuery, // Use preprocessed query or original query
          history: currentMessages
            .filter((msg) => msg.id !== userMessage.id)
            .map((msg) => {
              const historyItem: HistoryItem = {
                role: msg.role,
                content:
                  msg.role === ROLE_ASSISTANT
                    ? msg.finalAnswer?.trim() || msg.content || ""
                    : msg.content || "",
              };
              // Include attachment info for historical messages so the agent
              // can reference files from previous turns
              if (msg.attachments && msg.attachments.length > 0) {
                historyItem.minio_files = msg.attachments.map((attachment) => ({
                  object_name: attachment.object_name || "",
                  name: attachment.name,
                  type: attachment.type,
                  size: attachment.size,
                  url: attachment.url || "",
                  presigned_url: attachment.presigned_url || "",
                  description: attachment.description || "",
                }));
              }
              return historyItem;
            }),
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
                    presigned_url: presignedUrls[attachment.name] || "",
                    description: description,
                  };
                })
              : undefined, // Use complete attachment object structure
        };

      // Only include conversation_id for existing conversations; omit for new ones
      // so backend can auto-create the conversation and emit conversation_created.
      if (currentConversationId != null) {
        runAgentParams.conversation_id = currentConversationId;
      }

      // Only add agent_id if it's not null
      if (agentIdForRun !== null) {
        runAgentParams.agent_id = agentIdForRun;
      }

      // Add selected model_id for agent run
      if (selectedModelId !== null) {
        runAgentParams.model_id = selectedModelId;
      }

      const reader = await conversationService.runAgent(
        runAgentParams,
        currentController.signal
      );

      if (currentConversationId != null) {
        conversationManagement.updateConversationAgentId(
          currentConversationId,
          agentIdForRun
        );
      }

      if (!reader) throw new Error("Response body is null");

      // Create dynamic setCurrentSessionMessages in handleSend function
      // setCurrentSessionMessages factory function. Once the backend emits a real
      // conversation_id via the conversation_created SSE event, subsequent writes
      // must be redirected to that conversation_id instead of the placeholder key.
      let resolvedTargetConversationId: number = id;
      const setCurrentSessionMessagesFactory =
        (
          targetConversationId: number
        ): React.Dispatch<React.SetStateAction<ChatMessageType[]>> =>
        (valueOrUpdater) => {
          setSessionMessages((prev) => {
            const realId = resolvedTargetConversationId;
            // If the target is the placeholder, also pull existing messages from
            // any real conversation_id we have migrated to.
            const prevArr = prev[realId] || [];
            let nextArr: ChatMessageType[];
            if (typeof valueOrUpdater === "function") {
              nextArr = (
                valueOrUpdater as (prev: ChatMessageType[]) => ChatMessageType[]
              )(prevArr);
            } else {
              nextArr = valueOrUpdater;
            }
            const nextState = { ...prev };
            nextState[realId] = [...nextArr];
            if (targetConversationId !== realId) {
              delete nextState[targetConversationId];
            }
            return nextState;
          });
        };

      // Create resetTimeout function for current conversation
      const resetTimeout = () => {
        const timeout = conversationTimeoutsRef.current.get(id);
        if (timeout) {
          clearTimeout(timeout);
        }
        const newTimeout = setTimeout(async () => {
          const controller = conversationControllersRef.current.get(id);
          if (controller && !controller.signal.aborted) {
            try {
              controller.abort(t("chatInterface.requestTimeout"));

              setSessionMessages((prev) => {
                const newMessages = { ...prev };
                const lastMsg = newMessages[id]?.[newMessages[id].length - 1];
                if (lastMsg && lastMsg.role === ROLE_ASSISTANT) {
                  lastMsg.error = t("chatInterface.requestTimeoutRetry");
                  lastMsg.isComplete = true;
                  lastMsg.thinking = undefined;
                }
                return newMessages;
              });

              try {
                await conversationService.stop(id);
              } catch (error) {
                log.error(t("chatInterface.stopTimeoutRequestFailed"), error);
              }
            } catch (error) {
              log.error(t("chatInterface.errorCancelingRequest"), error);
            }
          }
          conversationTimeoutsRef.current.delete(id);
        }, 120000);
        conversationTimeoutsRef.current.set(id, newTimeout);
      };

      // Before processing streaming response, set an initial timeout first
      resetTimeout();

      // Call streaming processing function to handle response
      await handleStreamResponse(
        reader as ReadableStreamDefaultReader<Uint8Array>,
        setCurrentSessionMessagesFactory(id),
        resetTimeout,
        stepIdCounter,
        setIsSwitchedConversation,
        (conversationId: number) => {
          // Backend auto-created a new conversation - migrate messages from the
          // placeholder to the real conversation ID and update frontend state.
          if (id !== conversationId) {
            resolvedTargetConversationId = conversationId;
            setSessionMessages((prev) => {
              const placeholderMessages = prev[id] || [];
              const { [id]: _, ...rest } = prev;
              return {
                ...rest,
                [conversationId]: placeholderMessages,
              };
            });
            conversationControllersRef.current.delete(id);
            conversationControllersRef.current.set(
              conversationId,
              currentController
            );
            // Clear the old timeout (which was bound to the placeholder key);
            // the active stream's resetTimeout() will re-create one as new chunks arrive.
            const oldTimeout = conversationTimeoutsRef.current.get(id);
            if (oldTimeout) {
              clearTimeout(oldTimeout);
              conversationTimeoutsRef.current.delete(id);
            }
            setStreamingConversations((prev) => {
              const newSet = new Set(prev);
              newSet.delete(id);
              newSet.add(conversationId);
              return newSet;
            });
            cid = conversationId;
          }
          conversationManagement.setSelectedConversationId(conversationId);
          conversationManagement.setConversationTitle(
            t("chatInterface.newConversation")
          );
          // Add the new conversation to the sidebar immediately so users see it
          // appear in the conversation list during streaming (not only after stream ends)
          conversationManagement.prependConversation(
            conversationId,
            t("chatInterface.newConversation"),
            agentIdForRun
          );
        },
        false, // isDebug: false for normal chat mode
        t
      );

      // Use the resolved conversation ID (may have changed via conversation_created event)
      const finalId = cid ?? id;

      await hydrateConversationMessageIds(finalId);

      // Reset all related states
      setIsLoading(false);
      setIsStreaming(false);

      // Clean up controller and timeout for current conversation
      conversationControllersRef.current.delete(finalId);
      const timeout = conversationTimeoutsRef.current.get(finalId);
      if (timeout) {
        clearTimeout(timeout);
        conversationTimeoutsRef.current.delete(finalId);
      }

      // Remove from streaming list when we have a valid conversation id
      setStreamingConversations((prev) => {
        const newSet = new Set(prev);
        newSet.delete(finalId);
        return newSet;
      });

      // When conversation is completed, only add to completed conversation list when user is not in current conversation interface
      const currentUserConversation =
        conversationManagement.selectedConversationId;
      if (currentUserConversation !== finalId) {
        setCompletedConversations((prev) => {
          const newSet = new Set(prev);
          newSet.add(finalId);
          return newSet;
        });
      }

      // For new conversations, refresh the conversation list after the stream to fetch
      // the auto-generated title created by the backend.
      if (currentConversationId == null) {
        try {
          const refreshed =
            await conversationManagement.fetchConversationList();
          const newDialog = refreshed.find(
            (dialog) => dialog.conversation_id === finalId
          );
          if (newDialog) {
            conversationManagement.setConversationTitle(
              newDialog.conversation_title || t("chatInterface.newConversation")
            );
          }
        } catch (error) {
          log.error(
            t("chatInterface.refreshDialogListFailedButContinue"),
            error
          );
        }
      }

      // Note: Save operation is already implemented in agent run API, no need to save again in frontend
    } catch (error) {
      // If user actively canceled, don't show error message
      const err = error as Error;
      if (cid != null) {
        const idForCatch = cid;
        if (err.name === "AbortError") {
          setSessionMessages((prev) => {
            const newMessages = { ...prev };
            const lastMsg =
              newMessages[idForCatch]?.[newMessages[idForCatch].length - 1];
            if (lastMsg && lastMsg.role === ROLE_ASSISTANT) {
              lastMsg.content = t("chatInterface.conversationStopped");
              lastMsg.isComplete = true;
              lastMsg.thinking = undefined; // Explicitly clear thinking state
            }
            return newMessages;
          });
        } else {
          log.error(t("chatInterface.errorLabel"), error);
          const errorMessage = t("chatInterface.errorProcessingRequest");
          setSessionMessages((prev) => {
            const newMessages = { ...prev };
            const lastMsg =
              newMessages[idForCatch]?.[newMessages[idForCatch].length - 1];
            if (lastMsg && lastMsg.role === ROLE_ASSISTANT) {
              lastMsg.content = errorMessage;
              lastMsg.isComplete = true;
              lastMsg.error = errorMessage;
              lastMsg.thinking = undefined; // Explicitly clear thinking state
            }
            return newMessages;
          });
        }
      }

      setIsLoading(false);
      setIsStreaming(false);

      // Clean up when we had a conversation id (cid is set after the guard in try)
      if (cid != null) {
        const idForCatch = cid;
        conversationControllersRef.current.delete(idForCatch);
        const timeout = conversationTimeoutsRef.current.get(idForCatch);
        if (timeout) {
          clearTimeout(timeout);
          conversationTimeoutsRef.current.delete(idForCatch);
        }
        setStreamingConversations((prev) => {
          const newSet = new Set(prev);
          newSet.delete(idForCatch);
          return newSet;
        });
        const currentUserConversation =
          conversationManagement.selectedConversationId;
        if (currentUserConversation !== idForCatch) {
          setCompletedConversations((prev) => {
            const newSet = new Set(prev);
            newSet.add(idForCatch);
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

    // Clear parameters that belong to the previous conversation.
    const url = new URL(window.location.href);
    const hasConversationParameters =
      url.searchParams.has("q") || url.searchParams.has("conversation_id");
    url.searchParams.delete("q");
    url.searchParams.delete("conversation_id");
    if (hasConversationParameters) {
      window.history.replaceState({}, "", url.toString());
    }

    // Wait for all state updates to complete
    await new Promise((resolve) => setTimeout(resolve, 0));

    // Ensure new conversation scrolls to bottom
    setShouldScrollToBottom(true);
  };

  // Helper to handle resume completion when agent finished during disconnect
  const handleResumeCompletion = (conversationId: number, status: string) => {
    // Clean up streaming state
    setStreamingConversations((prev) => {
      const newSet = new Set(prev);
      newSet.delete(conversationId);
      return newSet;
    });
    setIsStreaming(false);

    // Mark the message as complete in the UI
    setSessionMessages((prev) => {
      const messages = prev[conversationId];
      if (!messages || messages.length === 0) return prev;
      const newMessages = [...messages];
      const lastMsg = newMessages[newMessages.length - 1];
      if (lastMsg && lastMsg.role === ROLE_ASSISTANT) {
        newMessages[newMessages.length - 1] = {
          ...lastMsg,
          isComplete: true,
        };
      }
      return {
        ...prev,
        [conversationId]: newMessages,
      };
    });
  };

  // Helper to create a session messages updater for a specific conversation
  const createSessionMessagesUpdater = useCallback(
    (targetConversationId: number) => {
      return (valueOrUpdater: React.SetStateAction<ChatMessageType[]>) => {
        setSessionMessages((prev) => {
          const prevArr = prev[targetConversationId] || [];
          const nextArr =
            typeof valueOrUpdater === "function"
              ? (
                  valueOrUpdater as (
                    prev: ChatMessageType[]
                  ) => ChatMessageType[]
                )(prevArr)
              : valueOrUpdater;
          return {
            ...prev,
            [targetConversationId]: [...nextArr],
          };
        });
      };
    },
    []
  );

  // Helper to handle timeout expiration during resume streaming
  const handleResumeTimeout = useCallback(
    async (convId: number) => {
      const ctrl = conversationControllersRef.current.get(convId);
      if (ctrl && !ctrl.signal.aborted) {
        try {
          ctrl.abort(t("chatInterface.requestTimeout"));
          await conversationService.stop(convId);
        } catch (e) {
          log.error(t("chatInterface.stopTimeoutRequestFailed"), e);
        }
      }
      conversationTimeoutsRef.current.delete(convId);
    },
    [t]
  );

  // Helper to set up and trigger a timeout for resume streaming
  const startResumeTimeout = useCallback(
    (convId: number) => {
      const existingTimeout = conversationTimeoutsRef.current.get(convId);
      if (existingTimeout) {
        clearTimeout(existingTimeout);
      }
      const newTimeout = setTimeout(() => {
        handleResumeTimeout(convId);
      }, 120000);
      conversationTimeoutsRef.current.set(convId, newTimeout);
    },
    [handleResumeTimeout]
  );

  // Helper function to resume streaming after tab switch
  const resumeStreamingConversation = useCallback(
    async (conversationId: number, streamingMessage: StreamingMessage) => {
      const lastUnit = streamingMessage.last_unit;
      const resumeConfig: ResumeConfig = {
        streamingMessage,
        lastUnitIndex: lastUnit?.unit_index ?? -1,
      };

      // Create new AbortController for the resume request
      const controller = new AbortController();
      conversationControllersRef.current.set(conversationId, controller);

      let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;

      try {
        // Call resume API
        const response = await conversationService.runAgent(
          {
            query: "",
            conversation_id: conversationId,
            history: [],
            is_resume: true,
          },
          controller.signal
        );

        // Check if this is a JSON response (agent finished during disconnect)
        if (
          response &&
          typeof response === "object" &&
          "type" in response &&
          response.type === "json"
        ) {
          const jsonData = response.data as {
            status: string;
            message?: string;
          };
          handleResumeCompletion(conversationId, jsonData.status);
          return;
        }

        reader = response as ReadableStreamDefaultReader<Uint8Array>;
        if (!reader) {
          throw new Error("Response body is null");
        }

        // Set streaming state
        setStreamingConversations((prev) => {
          const newSet = new Set(prev);
          newSet.add(conversationId);
          return newSet;
        });
        setIsStreaming(true);

        // Set up timeout and call stream handler
        startResumeTimeout(conversationId);

        await handleStreamResponse(
          reader,
          createSessionMessagesUpdater(conversationId),
          () => startResumeTimeout(conversationId),
          stepIdCounter,
          setIsSwitchedConversation,
          () => {}, // onConversationCreated: no-op for resume mode
          false,
          t,
          resumeConfig
        );
      } catch (error) {
        log.error(t("chatInterface.resumeStreamFailed"), error);
      } finally {
        conversationControllersRef.current.delete(conversationId);
        setStreamingConversations((prev) => {
          const newSet = new Set(prev);
          newSet.delete(conversationId);
          return newSet;
        });
        setIsStreaming(false);
      }
    },
    [
      t,
      conversationService,
      conversationManagement,
      createSessionMessagesUpdater,
      startResumeTimeout,
      handleResumeCompletion,
    ]
  );

  // When switching conversation, automatically load messages
  const handleDialogClick = async (dialog: ConversationListItem) => {
    // When switching conversation, keep all SSE connections active
    // Do not cancel any conversation requests, let them continue running in the background

    // Use conversation management hook
    conversationManagement.handleConversationSelect(dialog);
    const conversationUrl = new URL(window.location.href);
    conversationUrl.searchParams.set(
      "conversation_id",
      String(dialog.conversation_id)
    );
    window.history.replaceState({}, "", conversationUrl.toString());
    restoreConversationAgent(dialog.agent_id ?? null);
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
    const isCurrentActive =
      dialog.conversation_id === conversationManagement.selectedConversationId;

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
            restoreConversationAgent(
              conversationData.agent_id ?? dialog.agent_id ?? null
            );
            const formattedMessages = await hydrateAutomationProposalMessages(
              formatConversationMessagesFromResponse(conversationData, t),
              dialog.conversation_id
            );

            // Update message array
            setSessionMessages((prev) => ({
              ...prev,
              [dialog.conversation_id]: formattedMessages,
            }));

            // Clear any previous error for this conversation
            conversationManagement.clearConversationLoadError(
              dialog.conversation_id
            );

            // Check if this conversation has an in-progress streaming message
            const streamingMessage = (
              conversationData as ApiConversationDetail & {
                streaming_message?: StreamingMessage;
              }
            ).streaming_message;
            if (streamingMessage && streamingMessage.status === "streaming") {
              // Resume streaming - wait for state to update first
              setTimeout(() => {
                resumeStreamingConversation(
                  dialog.conversation_id,
                  streamingMessage
                );
              }, 100);
            }

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

          conversationManagement.setConversationLoadErrorForId(
            dialog.conversation_id,
            "Failed to load conversation"
          );
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
          restoreConversationAgent(
            conversationData.agent_id ?? dialog.agent_id ?? null
          );
          const formattedMessages = await hydrateAutomationProposalMessages(
            formatConversationMessagesFromResponse(conversationData, t),
            dialog.conversation_id
          );

          // Update message array
          setSessionMessages((prev) => ({
            ...prev,
            [dialog.conversation_id]: formattedMessages,
          }));

          // Clear any previous error for this conversation
          conversationManagement.clearConversationLoadError(
            dialog.conversation_id
          );

          // Check if this conversation has an in-progress streaming message
          const streamingMessage = (
            conversationData as ApiConversationDetail & {
              streaming_message?: StreamingMessage;
            }
          ).streaming_message;
          if (streamingMessage && streamingMessage.status === "streaming") {
            // Resume streaming - wait for state to update first
            setTimeout(() => {
              resumeStreamingConversation(
                dialog.conversation_id,
                streamingMessage
              );
            }, 100);
          }

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

        conversationManagement.setConversationLoadErrorForId(
          dialog.conversation_id,
          "Failed to load conversation"
        );
      } finally {
        // ensure loading state is cleared
        setIsLoading(false);
        setIsLoadingHistoricalConversation(false);
      }
    }
  };
  handleDialogClickRef.current = handleDialogClick;

  useEffect(() => {
    if (
      linkedConversationHandledRef.current ||
      conversationManagement.conversationListQuery.isLoading
    ) {
      return;
    }

    const rawConversationId = new URL(window.location.href).searchParams.get(
      "conversation_id"
    );
    const conversationId = Number(rawConversationId);
    if (
      !rawConversationId ||
      !Number.isInteger(conversationId) ||
      conversationId <= 0
    ) {
      linkedConversationHandledRef.current = true;
      return;
    }

    const linkedConversation = conversationManagement.conversationList.find(
      (conversation) => conversation.conversation_id === conversationId
    );
    if (linkedConversation) {
      linkedConversationHandledRef.current = true;
      void handleDialogClickRef.current(linkedConversation);
      return;
    }

    if (conversationManagement.conversationListQuery.isFetched) {
      linkedConversationHandledRef.current = true;
    }
  }, [
    conversationManagement.conversationList,
    conversationManagement.conversationListQuery.isFetched,
    conversationManagement.conversationListQuery.isLoading,
  ]);

  // Add function to asynchronously load attachment URLs
  const loadAttachmentUrls = async (
    messages: ChatMessageType[],
    targetConversationId?: number
  ) => {
    // Create a copy to avoid directly modifying parameters
    const updatedMessages = [...messages];
    let hasUpdates = false;
    const conversationIdToUse =
      targetConversationId ?? conversationManagement.selectedConversationId;

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

    // If there are updates and we have a conversation id, set new message array
    if (hasUpdates && conversationIdToUse != null) {
      setSessionMessages((prev) => ({
        ...prev,
        [conversationIdToUse]: updatedMessages,
      }));
    }
  };

  // Add image error handling function
  const handleImageError = (imageUrl: string) => {
    log.error(t("chatInterface.imageLoadFailed"), imageUrl);

    // Remove failed images from messages
    setSessionMessages((prev) => {
      const newMessages = { ...prev };
      const lastMsg =
        newMessages[conversationManagement.selectedConversationId!]?.[
          newMessages[conversationManagement.selectedConversationId!].length - 1
        ];

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
    const currentController = conversationControllersRef.current.get(
      conversationManagement.selectedConversationId!
    );
    if (currentController) {
      try {
        currentController.abort(t("chatInterface.userManuallyStopped"));
      } catch (error) {
        log.error(t("chatInterface.errorCancelingRequest"), error);
      }
      conversationControllersRef.current.delete(
        conversationManagement.selectedConversationId!
      );
    }

    // Clear timeout timer for current conversation
    const currentTimeout = conversationTimeoutsRef.current.get(
      conversationManagement.selectedConversationId!
    );
    if (currentTimeout) {
      clearTimeout(currentTimeout);
      conversationTimeoutsRef.current.delete(
        conversationManagement.selectedConversationId!
      );
    }

    // Immediately update frontend state
    setIsStreaming(false);
    setIsLoading(false);

    // If no valid conversation ID, just reset frontend state
    if (conversationManagement.selectedConversationId == null) {
      return;
    }

    try {
      // Call backend stop API - this will stop both agent run and preprocess tasks
      await conversationService.stop(
        conversationManagement.selectedConversationId!
      );

      // Manually update messages, clear thinking state
      setSessionMessages((prev) => {
        const newMessages = { ...prev };
        const lastMsg =
          newMessages[conversationManagement.selectedConversationId!]?.[
            newMessages[conversationManagement.selectedConversationId!].length -
              1
          ];
        if (lastMsg && lastMsg.role === ROLE_ASSISTANT) {
          lastMsg.isComplete = true;
          lastMsg.thinking = undefined; // Explicitly clear thinking state
        }
        return newMessages;
      });

      // remove from streaming list
      setStreamingConversations((prev) => {
        const newSet = new Set(prev);
        newSet.delete(conversationManagement.selectedConversationId!);
        return newSet;
      });

      // when conversation is stopped, only add to completed conversations list when user is not in current conversation interface
      const currentUserConversation =
        conversationManagement.selectedConversationId;
      if (
        currentUserConversation != null &&
        currentUserConversation !==
          conversationManagement.selectedConversationId
      ) {
        setCompletedConversations((prev) => {
          const newSet = new Set(prev);
          newSet.add(conversationManagement.selectedConversationId!);
          return newSet;
        });
      }
    } catch (error) {
      log.error(t("chatInterface.stopConversationFailed"), error);

      // Optionally show error message
      setSessionMessages((prev) => {
        const newMessages = { ...prev };
        const lastMsg =
          newMessages[conversationManagement.selectedConversationId!]?.[
            newMessages[conversationManagement.selectedConversationId!].length -
              1
          ];
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
    if (
      conversationManagement.selectedConversationId &&
      newTitle !== conversationManagement.conversationTitle
    ) {
      try {
        await conversationManagement.updateConversationTitle(
          conversationManagement.selectedConversationId,
          newTitle
        );
      } catch (error) {
        log.error(t("chatInterface.renameFailed"), error);
      }
    }
  };

  // Handle message selection
  const handleMessageSelect = useCallback((messageId: string) => {
    setShowRightPanel(true);
    setSelectedMessageId(messageId);
  }, []);

  const hydrateConversationMessageIds = useCallback(
    async (conversationId: number) => {
      const messages = sessionMessagesRef.current[conversationId] || [];
      const missingIndexes = messages
        .map((msg, index) => ({ msg, index }))
        .filter(({ msg }) => typeof msg.message_id !== "number");

      if (missingIndexes.length === 0) {
        return;
      }

      const resolvedEntries = await Promise.all(
        missingIndexes.map(async ({ index }) => {
          try {
            const messageId = await conversationService.getMessageId(
              conversationId,
              index
            );
            return typeof messageId === "number"
              ? { index, messageId }
              : undefined;
          } catch (error) {
            log.error("Failed to hydrate message id", error);
            return undefined;
          }
        })
      );

      const resolvedMap = new Map<number, number>();
      resolvedEntries.forEach((entry) => {
        if (entry) {
          resolvedMap.set(entry.index, entry.messageId);
        }
      });

      if (resolvedMap.size === 0) {
        return;
      }

      setSessionMessages((prev) => {
        const current = prev[conversationId] || [];
        return {
          ...prev,
          [conversationId]: current.map((msg, index) =>
            typeof msg.message_id === "number" || !resolvedMap.has(index)
              ? msg
              : { ...msg, message_id: resolvedMap.get(index) as number }
          ),
        };
      });
    },
    []
  );

  const shareableUserMessageIds = currentMessages
    .filter(
      (msg) =>
        msg.role === MESSAGE_ROLES.USER && typeof msg.message_id === "number"
    )
    .map((msg) => msg.message_id as number);

  useEffect(() => {
    if (!isShareMode || !conversationManagement.selectedConversationId) {
      return;
    }
    const hasMissingMessageIds = currentMessages.some(
      (msg) => typeof msg.message_id !== "number"
    );
    if (hasMissingMessageIds) {
      hydrateConversationMessageIds(
        conversationManagement.selectedConversationId
      );
    }
  }, [
    currentMessages,
    hydrateConversationMessageIds,
    isShareMode,
    conversationManagement.selectedConversationId,
  ]);

  const toggleShareMode = async () => {
    const next = !isShareMode;
    if (!next) {
      setSelectedShareMessageIds(new Set());
      setIsShareMode(false);
      return;
    }

    if (conversationManagement.selectedConversationId) {
      await hydrateConversationMessageIds(
        conversationManagement.selectedConversationId
      );
    }
    setIsShareMode(true);
  };

  const toggleShareMessage = (messageId: number) => {
    setSelectedShareMessageIds((prev) => {
      const next = new Set(prev);
      if (next.has(messageId)) {
        next.delete(messageId);
      } else {
        next.add(messageId);
      }
      return next;
    });
  };

  const handleToggleShareAll = () => {
    setSelectedShareMessageIds((prev) => {
      if (
        shareableUserMessageIds.length > 0 &&
        prev.size === shareableUserMessageIds.length
      ) {
        return new Set();
      }
      return new Set(shareableUserMessageIds);
    });
  };

  const handleCreateShare = async () => {
    if (!conversationManagement.selectedConversationId) {
      message.warning(
        t(
          "chatInterface.noConversationSelected",
          "Please select a conversation first"
        )
      );
      return;
    }
    if (selectedShareMessageIds.size === 0) {
      message.warning(
        t(
          "chatInterface.selectShareMessages",
          "Please select at least one Q&A pair"
        )
      );
      return;
    }

    setIsCreatingShare(true);
    try {
      const allSelected =
        selectedShareMessageIds.size === shareableUserMessageIds.length;
      const result = await conversationService.createShare({
        conversationId: conversationManagement.selectedConversationId,
        mode: allSelected ? "all" : "selected",
        selected_user_message_ids: Array.from(selectedShareMessageIds),
      });
      const locale = i18n.language?.startsWith("en") ? "en" : "zh";
      const shareUrl = await buildShareUrl(result.share_id, locale);
      const copied = await copyTextToClipboard(shareUrl);

      setIsShareMode(false);
      setSelectedShareMessageIds(new Set());

      if (copied) {
        message.success(
          t("chatInterface.shareLinkCopied", "Share link copied")
        );
      } else {
        setManualShareUrl(shareUrl);
        message.warning(
          t(
            "chatInterface.shareCreatedCopyFailed",
            "Share link created, but copy is unavailable"
          )
        );
      }
    } catch (error) {
      log.error("Failed to create share", error);
      message.error(
        t("chatInterface.shareCreateFailed", "Failed to create share link")
      );
    } finally {
      setIsCreatingShare(false);
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
    <Layout hasSider className="flex h-full">
      <ChatSidebar
        streamingConversations={streamingConversations}
        completedConversations={completedConversations}
        conversationManagement={conversationManagement}
        onConversationSelect={handleDialogClick}
        automationConversationIds={automationConversationIds}
      />

      <Layout className="flex-1 flex flex-col overflow-hidden min-w-0">
        <div className="flex flex-1 overflow-hidden">
          <div className="flex-1 flex flex-col">
            <ChatHeader
              title={conversationManagement.conversationTitle}
              onRename={handleTitleRename}
              onShareClick={toggleShareMode}
              isShareMode={isShareMode}
              hasAutomation={
                conversationManagement.selectedConversationId !== null &&
                automationConversationIds.has(
                  conversationManagement.selectedConversationId
                )
              }
            />

            {isShareMode && (
              <div className="mx-4 mb-2 flex items-center justify-between rounded-md border border-slate-200 bg-white px-3 py-2 shadow-sm">
                <Checkbox
                  checked={
                    shareableUserMessageIds.length > 0 &&
                    selectedShareMessageIds.size ===
                      shareableUserMessageIds.length
                  }
                  indeterminate={
                    selectedShareMessageIds.size > 0 &&
                    selectedShareMessageIds.size <
                      shareableUserMessageIds.length
                  }
                  onChange={handleToggleShareAll}
                >
                  {t("common.selectAll", "Select all")}
                </Checkbox>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-slate-500">
                    {t("chatInterface.selectedShareCount", {
                      defaultValue: "Selected {{count}}",
                      count: selectedShareMessageIds.size,
                    })}
                  </span>
                  <Button onClick={toggleShareMode}>
                    {t("common.cancel", "Cancel")}
                  </Button>
                  <Button
                    type="primary"
                    loading={isCreatingShare}
                    onClick={handleCreateShare}
                  >
                    {t("chatInterface.copyShareLink", "Copy link")}
                  </Button>
                </div>
              </div>
            )}

            <Modal
              open={!!manualShareUrl}
              title={t("chatInterface.shareLinkReady", "Share link ready")}
              okText={t("chatInterface.copyShareLink", "Copy link")}
              cancelText={t("common.close", "Close")}
              onCancel={() => setManualShareUrl(null)}
              onOk={async () => {
                if (!manualShareUrl) return;
                const copied = await copyTextToClipboard(manualShareUrl);
                if (copied) {
                  message.success(
                    t("chatInterface.shareLinkCopied", "Share link copied")
                  );
                  setManualShareUrl(null);
                } else {
                  message.warning(
                    t(
                      "chatInterface.shareManualCopyRequired",
                      "Please copy the link manually"
                    )
                  );
                }
              }}
            >
              <p className="mb-3 text-sm text-slate-600">
                {t(
                  "chatInterface.shareManualCopyHint",
                  "The share link has been created. Copy it from the field below."
                )}
              </p>
              <Input
                value={manualShareUrl || ""}
                readOnly
                onClick={(event) => event.currentTarget.select()}
              />
            </Modal>

            <ChatStreamMain
              messages={currentMessages}
              input={input}
              isLoading={isLoading}
              isStreaming={isCurrentConversationStreaming}
              isLoadingHistoricalConversation={isLoadingHistoricalConversation}
              conversationLoadError={
                conversationManagement.conversationLoadError[
                  conversationManagement.selectedConversationId || 0
                ]
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
              currentConversationId={
                conversationManagement.selectedConversationId ?? undefined
              }
              shouldScrollToBottom={shouldScrollToBottom}
              selectedAgentId={selectedAgentId}
              onAgentSelect={handleAgentSelectWithGreeting}
              onCitationHover={clearCompletedIndicator}
              onScroll={clearCompletedIndicator}
              agentGreeting={agentGreeting}
              agentExampleQuestions={agentExampleQuestions}
              shareMode={isShareMode}
              selectedShareMessageIds={selectedShareMessageIds}
              onToggleShareMessage={toggleShareMessage}
              agentModelIds={agentModelIds}
              agentModelNames={agentModelNames}
              availableModels={availableModels}
              selectedModelId={selectedModelId}
              onModelSelect={setSelectedModelId}
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
      </Layout>
    </Layout>
  );
}
