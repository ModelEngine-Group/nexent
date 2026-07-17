"use client";

import type React from "react";

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { v4 as uuidv4 } from "uuid";
import { useTranslation } from "react-i18next";

import { ROLE_ASSISTANT } from "@/const/agentConfig";
import { MESSAGE_ROLES } from "@/const/chatConfig";
import { useModelList } from "@/hooks/model/useModelList";
import { searchAgentInfo } from "@/services/agentConfigService";
import { conversationService } from "@/services/conversationService";
import { storageService } from "@/services/storageService";
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
} from "@/lib/chat/chatAttachmentUtils";
import {
  ConversationListItem,
  ApiConversationDetail,
  HistoryItem,
} from "@/types/chat";
import { ChatMessageType } from "@/types/chat";
import {
  handleStreamResponse,
  ResumeConfig,
  StreamingMessage,
} from "@/app/chat/streaming/chatStreamHandler";
import { formatConversationMessagesFromResponse } from "@/lib/chatMessageExtractor";
import {
  parseNl2AgentDraftMap,
  resolveNl2AgentDraftAgentId,
} from "@/lib/chat/nl2agentDraftContext";
import { Nl2AgentWorkflowProvider } from "@/components/nl2agent/Nl2AgentWorkflowContext";
import {
  isNl2AgentAutoContinueText,
  nl2AgentContinuationScopeKey,
} from "@/lib/chat/nl2agentContinuation";
import { resolveNl2AgentSendRequest } from "@/lib/chat/nl2agentSendRequest";
import { resolveNl2AgentSessionByConversation } from "@/services/nl2agentService";

import { Button, Checkbox, Layout, message } from "antd";
import log from "@/lib/logger";

const stepIdCounter = { current: 0 };
const NL2AGENT_DRAFT_AGENT_ID_KEY = "nl2agent_draft_agent_id";
const NL2AGENT_CONVERSATION_ID_KEY = "nl2agent_conversation_id";
const NL2AGENT_DRAFT_MAP_KEY = "nl2agent_draft_by_conversation";
type RunAgentParams = Parameters<typeof conversationService.runAgent>[0];
type ConversationDetailWithStreaming = ApiConversationDetail & {
  streaming_message?: StreamingMessage;
};

const parseStoredNumber = (value: string | null): number | null => {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const readNl2AgentDraftMap = (): Record<string, number> => {
  if (typeof window === "undefined") return {};
  return parseNl2AgentDraftMap(localStorage.getItem(NL2AGENT_DRAFT_MAP_KEY));
};

const persistNl2AgentDraftForConversation = (
  conversationId: number,
  draftAgentId: number
) => {
  if (typeof window === "undefined") return;
  const draftMap = readNl2AgentDraftMap();
  draftMap[String(conversationId)] = draftAgentId;
  localStorage.setItem(NL2AGENT_DRAFT_MAP_KEY, JSON.stringify(draftMap));
};

const getNl2AgentDraftForConversation = (
  conversationId: number | null
): number | null => {
  if (conversationId == null) return null;
  return readNl2AgentDraftMap()[String(conversationId)] ?? null;
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
  const [, setIsSwitchedConversation] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const { t, i18n } = useTranslation("common");

  // Use conversation management hook
  const conversationManagement = useConversationManagement();

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
  // If a historical conversation is being loaded and there are no cached messages, return an empty array to avoid displaying error content
  const currentMessages = useMemo(
    () =>
      conversationManagement.selectedConversationId
        ? sessionMessages[conversationManagement.selectedConversationId] || []
        : [],
    [conversationManagement.selectedConversationId, sessionMessages]
  );

  // Monitor changes in currentMessages
  // Calculate if the current conversation is streaming
  const isCurrentConversationStreaming =
    conversationManagement.selectedConversationId != null
      ? streamingConversations.has(
          conversationManagement.selectedConversationId
        )
      : false;

  // Add attachment state management
  const [attachments, setAttachments] = useState<FilePreview[]>([]);
  const [fileUrls, setFileUrls] = useState<{ [id: string]: string }>({});

  const [, setIsStreaming] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null); // Add AbortController reference
  const timeoutRef = useRef<NodeJS.Timeout | null>(null); // Add timeout reference

  // Add a state to track if we're loading a historical conversation
  const [isLoadingHistoricalConversation, setIsLoadingHistoricalConversation] =
    useState(false);

  // Add a state to track completed conversations that haven't been viewed yet
  const [completedConversations, setCompletedConversations] = useState<
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
  const [nl2agentDraftAgentId, setNl2agentDraftAgentId] = useState<
    number | null
  >(null);
  const [nl2agentConversationId, setNl2agentConversationId] = useState<
    number | null
  >(null);
  const activeNl2AgentDraftAgentId = resolveNl2AgentDraftAgentId(
    conversationManagement.selectedConversationId,
    readNl2AgentDraftMap(),
    nl2agentConversationId,
    nl2agentDraftAgentId
  );
  const activeConversationIdRef = useRef<number | null>(null);
  const activeNl2AgentDraftIdRef = useRef<number | null>(null);
  const nonNl2AgentConversationIdsRef = useRef<Set<number>>(new Set());
  activeConversationIdRef.current =
    conversationManagement.selectedConversationId;
  activeNl2AgentDraftIdRef.current = activeNl2AgentDraftAgentId;

  const resolvePersistedDraftAgentId = useCallback(
    async (conversationId: number): Promise<number | null> => {
      const localDraftAgentId = getNl2AgentDraftForConversation(conversationId);
      if (localDraftAgentId !== null) return localDraftAgentId;
      if (nonNl2AgentConversationIdsRef.current.has(conversationId))
        return null;
      try {
        const session =
          await resolveNl2AgentSessionByConversation(conversationId);
        if (session === null) {
          nonNl2AgentConversationIdsRef.current.add(conversationId);
          return null;
        }
        persistNl2AgentDraftForConversation(
          conversationId,
          session.draft_agent_id
        );
        if (activeConversationIdRef.current === conversationId) {
          setNl2agentConversationId(conversationId);
          setNl2agentDraftAgentId(session.draft_agent_id);
        }
        return session.draft_agent_id;
      } catch (error) {
        log.warn("Failed to resolve persisted NL2AGENT session", error);
        return null;
      }
    },
    []
  );

  useEffect(() => {
    const conversationId = conversationManagement.selectedConversationId;
    if (conversationId !== null) {
      void resolvePersistedDraftAgentId(conversationId);
    }
  }, [
    conversationManagement.selectedConversationId,
    resolvePersistedDraftAgentId,
  ]);
  const [agentGreeting, setAgentGreeting] = useState<string | null>(null);
  const [agentExampleQuestions, setAgentExampleQuestions] = useState<string[]>(
    []
  );
  const [isShareMode, setIsShareMode] = useState(false);
  const [selectedShareMessageIds, setSelectedShareMessageIds] = useState<
    Set<number>
  >(new Set());
  const [isCreatingShare, setIsCreatingShare] = useState(false);
  const [agentModelIds, setAgentModelIds] = useState<number[]>([]);
  const [agentModelNames, setAgentModelNames] = useState<string[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<number | null>(null);

  useEffect(() => {
    sessionMessagesRef.current = sessionMessages;
  }, [sessionMessages]);

  const handleAgentSelectWithGreeting = (
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
  };

  useEffect(() => {
    let isMounted = true;

    const agentId = sessionStorage.getItem("selectedAgentId");
    const draftAgentId = parseStoredNumber(
      sessionStorage.getItem(NL2AGENT_DRAFT_AGENT_ID_KEY)
    );
    const conversationId = parseStoredNumber(
      sessionStorage.getItem(NL2AGENT_CONVERSATION_ID_KEY)
    );

    // Set selected agent ID from sessionStorage if it exists
    if (agentId) {
      setSelectedAgentId(agentId);
      const numericAgentId = Number(agentId);
      if (Number.isFinite(numericAgentId)) {
        void searchAgentInfo(numericAgentId)
          .then((result) => {
            if (!isMounted || !result.success || !result.data) {
              return;
            }

            const modelIds = Array.isArray(result.data.model_ids)
              ? result.data.model_ids
                  .map((id: unknown) => Number(id))
                  .filter((id: number) => Number.isFinite(id))
              : [];
            const rawModelNames = Array.isArray(result.data.model_names)
              ? result.data.model_names
              : [];
            const modelNames = modelIds.map(
              (modelId, index) => rawModelNames[index] || String(modelId)
            );

            setAgentGreeting(result.data.greeting_message || null);
            setAgentExampleQuestions(result.data.example_questions || []);
            setAgentModelIds(modelIds);
            setAgentModelNames(modelNames);
            setSelectedModelId(modelIds.length > 0 ? modelIds[0] : null);
          })
          .catch((error) => {
            log.error("Failed to hydrate selected agent details", error);
          });
      }
      sessionStorage.removeItem("selectedAgentId");
    }
    if (draftAgentId != null) {
      setNl2agentDraftAgentId(draftAgentId);
      sessionStorage.removeItem(NL2AGENT_DRAFT_AGENT_ID_KEY);
    }
    if (conversationId != null) {
      setNl2agentConversationId(conversationId);
      conversationManagement.setSelectedConversationId(conversationId);
      conversationManagement.setIsNewConversation(false);
      sessionStorage.removeItem(NL2AGENT_CONVERSATION_ID_KEY);

      if (draftAgentId != null) {
        persistNl2AgentDraftForConversation(conversationId, draftAgentId);
      }

      conversationManagement
        .fetchConversationList()
        .then((dialogList) => {
          const dialog = dialogList.find(
            (item) => item.conversation_id === conversationId
          );
          if (dialog) {
            conversationManagement.setConversationTitle(
              dialog.conversation_title
            );
          }
        })
        .catch((error) => {
          log.error(
            t("chatInterface.refreshDialogListFailedButContinue"),
            error
          );
        });
    }
    // Consume one-shot sessionStorage handoff values only when the chat page opens.
    return () => {
      isMounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    const handlePageClick = () => {
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
  }, [t]);

  const handleSend = async (
    autoContinueText?: string,
    expectedConversationId?: number | null,
    expectedDraftAgentId?: number | null
  ) => {
    const { isAutoContinue, outgoingText, outgoingAttachments } =
      resolveNl2AgentSendRequest({
        autoContinueText,
        input,
        attachments,
        activeConversationId: activeConversationIdRef.current,
        activeDraftAgentId: activeNl2AgentDraftIdRef.current,
        expectedConversationId,
        expectedDraftAgentId,
      });
    if (!outgoingText && outgoingAttachments.length === 0) return;
    if (isAutoContinue && (isLoading || isCurrentConversationStreaming)) {
      throw new Error("The conversation is already running.");
    }

    // Flag to track if we should reset button states in finally block
    const shouldResetButtonStates = true;

    // If in new conversation state, switch to conversation state after sending message
    // Save the value to local variable before state update for title generation logic
    let shouldGenerateTitle = conversationManagement.isNewConversation;
    if (conversationManagement.isNewConversation) {
      conversationManagement.setIsNewConversation(false);
    }

    // Ensure right sidebar doesn't auto-expand when sending new message
    setSelectedMessageId(undefined);
    setShowRightPanel(false);

    // Handle user message content
    const userMessageId = uuidv4();
    const userMessageContent = outgoingText;

    // Get current conversation ID (null when new conversation)
    let currentConversationId = conversationManagement.selectedConversationId;
    let cid: number | null = null; // set after guard, used in try/catch/finally

    // Prepare attachment information
    // Handle file upload
    let uploadedFileUrls: Record<string, string> = {};
    let objectNames: Record<string, string> = {}; // Add object name mapping
    let presignedUrls: Record<string, string> = {}; // Store presigned URLs for external MCP tool access

    if (outgoingAttachments.length > 0) {
      // Show loading state
      setIsLoading(true);

      // Use preprocessing function to upload attachments
      const uploadResult = await uploadAttachments(outgoingAttachments, t);
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

      const missingUploads = outgoingAttachments.filter(
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
      outgoingAttachments,
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
      attachments:
        messageAttachments.length > 0 ? messageAttachments : undefined,
    };

    // Clear input box and attachments
    if (!isAutoContinue) {
      setInput("");
      setAttachments([]);
    }

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
      if (currentConversationId == null) {
        if (nl2agentConversationId != null) {
          currentConversationId = nl2agentConversationId;
          shouldGenerateTitle = false;
          conversationManagement.setSelectedConversationId(
            currentConversationId
          );
          conversationManagement.setIsNewConversation(false);

          try {
            const dialogList =
              await conversationManagement.fetchConversationList();
            const dialog = dialogList.find(
              (dialog) => dialog.conversation_id === currentConversationId
            );
            if (dialog) {
              conversationManagement.setConversationTitle(
                dialog.conversation_title
              );
            }
          } catch (error) {
            log.error(
              t("chatInterface.refreshDialogListFailedButContinue"),
              error
            );
          }
        } else {
          // No conversation selected: create new conversation first
          try {
            const createData = await conversationService.create(
              t("chatInterface.newConversation")
            );
            currentConversationId = createData.conversation_id;

            // Update current session state
            conversationManagement.setSelectedConversationId(
              currentConversationId
            );
            conversationManagement.setConversationTitle(
              createData.conversation_title ||
                t("chatInterface.newConversation")
            );

            // After creating new conversation, add it to streaming list
            setStreamingConversations((prev) => {
              const newSet = new Set(prev).add(createData.conversation_id);
              return newSet;
            });

            // Refresh conversation list
            try {
              const dialogList =
                await conversationManagement.fetchConversationList();
              const newDialog = dialogList.find(
                (dialog) => dialog.conversation_id === currentConversationId
              );
              if (newDialog) {
                conversationManagement.setSelectedConversationId(
                  currentConversationId
                );
              }
            } catch (error) {
              log.error(
                t("chatInterface.refreshDialogListFailedButContinue"),
                error
              );
            }
          } catch (error) {
            log.error(t("chatInterface.createDialogFailedButContinue"), error);
            // Reset button states when conversation creation fails
            setIsLoading(false);
            setIsStreaming(false);
            return;
          }
        }
      }

      // Type guard: we have a number here (either from selection or from create above)
      if (currentConversationId == null) return;
      const id = currentConversationId;
      cid = id;

      // Register controller and streaming state for this conversation
      conversationControllersRef.current.set(id, currentController);
      setStreamingConversations((prev) => {
        const newSet = new Set(prev);
        newSet.add(id);
        return newSet;
      });

      // Now add messages after conversation is created/confirmed
      // 1. When sending user message, complete ChatMessageType fields
      setSessionMessages((prev) => ({
        ...prev,
        [id]: [
          ...(prev[id] || []),
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
        [id]: [
          ...(prev[id] || []),
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

      if (outgoingAttachments.length > 0) {
        // Skip preprocessing - directly use original content
        // No preprocessing UI will be shown
        const result = await preprocessAttachments(
          userMessage.content,
          outgoingAttachments,
          currentController.signal,
          () => {}, // Empty progress callback - won't be called
          t,
          currentConversationId
        );

        finalQuery = result.finalQuery;
        fileDescriptionsMap = result.fileDescriptions || {};
      }

      // Send request to backend API, add signal parameter
      const runAgentParams: RunAgentParams = {
        query: finalQuery, // Use preprocessed query or original query
        conversation_id: id,
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

      // Only add agent_id if it's not null
      if (selectedAgentId !== null) {
        runAgentParams.agent_id = Number(selectedAgentId);
      }

      const draftAgentIdForRun =
        resolveNl2AgentDraftAgentId(
          id,
          readNl2AgentDraftMap(),
          nl2agentConversationId,
          nl2agentDraftAgentId
        ) ?? (await resolvePersistedDraftAgentId(id));
      if (draftAgentIdForRun !== null) {
        runAgentParams.draft_agent_id = draftAgentIdForRun;
      }

      // Add selected model_id for agent run
      if (selectedModelId !== null) {
        runAgentParams.model_id = selectedModelId;
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
        shouldGenerateTitle,
        conversationManagement.setConversationTitle,
        conversationManagement.fetchConversationList,
        id,
        conversationService,
        false, // isDebug: false for normal chat mode
        t
      );

      await hydrateConversationMessageIds(id);

      // Reset all related states
      setIsLoading(false);
      setIsStreaming(false);

      // Clean up controller and timeout for current conversation
      conversationControllersRef.current.delete(id);
      const timeout = conversationTimeoutsRef.current.get(id);
      if (timeout) {
        clearTimeout(timeout);
        conversationTimeoutsRef.current.delete(id);
      }

      // Remove from streaming list when we have a valid conversation id
      setStreamingConversations((prev) => {
        const newSet = new Set(prev);
        newSet.delete(id);
        return newSet;
      });

      // When conversation is completed, only add to completed conversation list when user is not in current conversation interface
      const currentUserConversation =
        conversationManagement.selectedConversationId;
      if (currentUserConversation !== id) {
        setCompletedConversations((prev) => {
          const newSet = new Set(prev);
          newSet.add(id);
          return newSet;
        });
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
      if (isAutoContinue) throw error;
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

  // Helper to handle resume completion when agent finished during disconnect
  const handleResumeCompletion = useCallback((conversationId: number) => {
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
  }, []);

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
        const draftAgentId = await resolvePersistedDraftAgentId(conversationId);
        const runAgentParams: RunAgentParams = {
          query: "",
          conversation_id: conversationId,
          history: [],
          is_resume: true,
        };
        if (draftAgentId !== null) {
          runAgentParams.draft_agent_id = draftAgentId;
        }

        // Call resume API
        const response = await conversationService.runAgent(
          runAgentParams,
          controller.signal
        );

        // Check if this is a JSON response (agent finished during disconnect)
        if (
          response &&
          typeof response === "object" &&
          "type" in response &&
          response.type === "json"
        ) {
          handleResumeCompletion(conversationId);
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
          false,
          conversationManagement.setConversationTitle,
          conversationManagement.fetchConversationList,
          conversationId,
          conversationService,
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
      conversationManagement,
      createSessionMessagesUpdater,
      startResumeTimeout,
      handleResumeCompletion,
      resolvePersistedDraftAgentId,
    ]
  );

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
            const formattedMessages = formatConversationMessagesFromResponse(
              conversationData,
              t
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
              conversationData as ConversationDetailWithStreaming
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
          const formattedMessages = formatConversationMessagesFromResponse(
            conversationData,
            t
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
            conversationData as ConversationDetailWithStreaming
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
        msg.role === MESSAGE_ROLES.USER &&
        typeof msg.message_id === "number" &&
        !isNl2AgentAutoContinueText(msg.content)
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
      const shareUrl = `${window.location.origin}/${locale}/share/${result.share_id}`;
      await navigator.clipboard.writeText(shareUrl);
      message.success(t("chatInterface.shareLinkCopied", "Share link copied"));
      setIsShareMode(false);
      setSelectedShareMessageIds(new Set());
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
  }, [conversationManagement, t]);

  return (
    <>
      <Layout hasSider className="flex h-full">
        <ChatSidebar
          streamingConversations={streamingConversations}
          completedConversations={completedConversations}
          conversationManagement={conversationManagement}
          onConversationSelect={handleDialogClick}
        />

        <Layout className="flex-1 flex flex-col overflow-hidden min-w-0">
          <div className="flex flex-1 overflow-hidden">
            <div className="flex-1 flex flex-col">
              <ChatHeader
                title={conversationManagement.conversationTitle}
                onRename={handleTitleRename}
                onShareClick={toggleShareMode}
                isShareMode={isShareMode}
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

              <Nl2AgentWorkflowProvider
                enabled={activeNl2AgentDraftAgentId != null}
                scopeKey={nl2AgentContinuationScopeKey(
                  conversationManagement.selectedConversationId,
                  activeNl2AgentDraftAgentId
                )}
                onContinue={(text) =>
                  handleSend(
                    text,
                    conversationManagement.selectedConversationId,
                    activeNl2AgentDraftAgentId
                  )
                }
              >
                <ChatStreamMain
                  messages={currentMessages}
                  input={input}
                  isLoading={isLoading}
                  isStreaming={isCurrentConversationStreaming}
                  isLoadingHistoricalConversation={
                    isLoadingHistoricalConversation
                  }
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
                  nl2AgentDraftAgentId={activeNl2AgentDraftAgentId}
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
              </Nl2AgentWorkflowProvider>
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
    </>
  );
}
