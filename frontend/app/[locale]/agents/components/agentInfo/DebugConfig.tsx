"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Paperclip, X, AlertCircle } from "lucide-react";

import { Input, Select, Switch, message as antMessage } from "antd";

import { conversationService } from "@/services/conversationService";
import { ChatMessageType, FilePreview } from "@/types/chat";
import { handleStreamResponse } from "@/app/chat/streaming/chatStreamHandler";
import { ChatModelSelector } from "@/app/chat/components/chatModelSelector";
import { MESSAGE_ROLES, chatConfig } from "@/const/chatConfig";
import log from "@/lib/logger";
import {
  getCachedDebugError,
  cacheDebugError,
  clearCachedDebugError,
} from "@/lib/agentDebugErrorCache";
import {
  cleanupAttachmentUrls,
  buildMinioFilePayload,
} from "@/lib/chat/chatAttachmentUtils";
import {
  getFileExtension,
  getFileIcon,
  MAX_FILE_COUNT,
  MAX_FILE_SIZE,
} from "@/lib/chat/fileIconUtils";
import { useModelList } from "@/hooks/model/useModelList";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useAgentInfo } from "@/hooks/agent/useAgentInfo";
import DebugMessageList from "./DebugMessageList";
import DebugOptimizeModal from "./DebugOptimizeModal";
import { useCompareStream } from "./useCompareStream";

// Check if a file type is supported
const isSupportedFile = (extension: string, fileType: string): boolean => {
  const isImage = fileType.startsWith("image/") || chatConfig.imageExtensions.includes(extension);
  const isDocument = chatConfig.documentExtensions.includes(extension) || fileType === "application/pdf" || fileType.includes("officedocument");
  const isSupportedTextFile = chatConfig.supportedTextExtensions.includes(extension) || fileType === "text/csv" || fileType === "text/plain";
  const isMedia = fileType.startsWith("audio/") || fileType.startsWith("video/") || chatConfig.audioExtensions.includes(extension) || chatConfig.videoExtensions.includes(extension);
  return isImage || isDocument || isSupportedTextFile || isMedia;
};

// Agent debugging component Props interface
interface AgentDebuggingProps {
  onStop: () => void;
  onClear: () => void;
  inputQuestion: string;
  onInputChange: (value: string) => void;
  onSend: () => void;
  isStreaming: boolean;
  isCompareStreaming?: boolean;
  messages: ChatMessageType[];
  onOptimizeReply?: (params: {
    userQuestion: string;
    assistantAnswer: string;
    history: Array<{ role: string; content: string }>;
  }) => void;
  comparePanel?: React.ReactNode;
  showCompare?: boolean;
  onOpenCompare?: () => void;
  compareDisabled?: boolean;
  isCompareMode?: boolean;
  attachments: FilePreview[];
  onFileSelect: (files: File[]) => void;
  onRemoveAttachment: (id: string) => void;
  modelIds?: number[];
  modelNames?: string[];
  selectedModelId?: number | null;
  onModelSelect?: (modelId: number | null) => void;
}

// Main component Props interface
interface DebugConfigProps {
  agentId?: number | null; // Make agentId an optional prop
}


/**
 * Agent debugging component
 */
function AgentDebugging({
  onStop,
  onClear,
  inputQuestion,
  onInputChange,
  onSend,
  isStreaming,
  isCompareStreaming = false,
  messages,
  onOptimizeReply,
  comparePanel,
  showCompare,
  onOpenCompare,
  compareDisabled,
  isCompareMode,
  attachments,
  onFileSelect,
  onRemoveAttachment,
  modelIds,
  modelNames,
  selectedModelId,
  onModelSelect,
}: AgentDebuggingProps & {
  modelIds: number[];
  modelNames: string[];
  selectedModelId: number | null;
  onModelSelect: (modelId: number | null) => void;
}) {
  const { t } = useTranslation();
  const isInputDisabled = isStreaming || (isCompareMode && isCompareStreaming);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Handle file input change
  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    onFileSelect(Array.from(files));
    e.target.value = "";
  };

  // Auto-dismiss error message
  useEffect(() => {
    if (errorMessage) {
      const timer = setTimeout(() => setErrorMessage(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [errorMessage]);

  return (
    <div className="flex flex-col h-full min-h-0 p-4">
      <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
        {isCompareMode ? (
          <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
            {comparePanel}
          </div>
        ) : (
          <div className="flex flex-col gap-4 flex-1 min-h-0 overflow-hidden">
            {/* Message display area */}
            <DebugMessageList
              messages={messages}
              isStreaming={isStreaming}
              onOptimizeReply={onOptimizeReply}
            />
          </div>
        )}

        {/* Attachment preview chips */}
        {attachments.length > 0 && (
          <div
            className="flex flex-wrap gap-1 mt-2 max-h-[80px] overflow-y-auto"
            style={{
              scrollbarWidth: "thin",
              scrollbarColor: "#d1d5db transparent",
            }}
          >
            {attachments.map((attachment) => (
              <div
                key={attachment.id}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-gray-200 bg-white text-xs hover:bg-gray-50 transition-colors"
              >
                {attachment.type === chatConfig.filePreviewTypes.image && attachment.previewUrl ? (
                  <img
                    src={attachment.previewUrl}
                    alt={attachment.file.name}
                    className="w-4 h-4 object-cover rounded flex-shrink-0"
                  />
                ) : (
                  <span className="flex-shrink-0">
                    {getFileIcon(attachment.file.name, attachment.file.type, 16)}
                  </span>
                )}
                <span
                  className="truncate max-w-[100px] text-gray-700"
                  title={attachment.file.name}
                >
                  {attachment.file.name}
                </span>
                <button
                  onClick={() => onRemoveAttachment(attachment.id)}
                  className="flex-shrink-0 text-gray-400 hover:text-red-500 transition-colors"
                  title={t("chatInput.remove")}
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Error message */}
        {errorMessage && (
          <div className="flex items-center gap-1 mt-1 text-xs text-red-600">
            <AlertCircle className="h-3 w-3" />
            <span>{errorMessage}</span>
          </div>
        )}

        <div className="flex items-center gap-2 mt-auto pt-4">
        {/* Paperclip file upload button */}
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={isInputDisabled}
          className="min-w-[32px] h-8 px-1.5 rounded-md flex items-center justify-center border border-gray-200 bg-white hover:bg-gray-100 text-gray-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          title={t("chatInput.uploadFiles")}
          style={{ border: "" }}
        >
          <Paperclip className="h-4 w-4" />
          <input
            type="file"
            ref={fileInputRef}
            className="hidden"
            onChange={handleFileInputChange}
            accept={`image/*,audio/*,video/*,${Object.values(chatConfig.fileIcons).flat().map(ext => '.' + ext).join(',')}`}
            multiple
          />
        </button>
        <Input
          value={inputQuestion}
          onChange={(e) => onInputChange(e.target.value)}
          placeholder={t("agent.debug.placeholder")}
          onPressEnter={onSend}
          disabled={isInputDisabled}
          className="flex-1"
        />
        {/* Model selector for debug mode */}
        {!isCompareMode && modelIds && modelIds.length > 0 && (
          <ChatModelSelector
            modelIds={modelIds}
            modelNames={modelNames}
            selectedModelId={selectedModelId}
            onModelSelect={onModelSelect || (() => {})}
            disabled={isInputDisabled}
          />
        )}
        <span className="px-2 py-1 text-xs rounded-md bg-gray-100 text-gray-600 whitespace-nowrap">
          {isCompareMode
            ? t("agent.debug.compareMode", "Compare mode")
            : t("agent.debug.defaultMode", "Default mode")}
        </span>
        {showCompare && (
          <div className="flex items-center gap-2 px-2 py-1 rounded-md border border-gray-200 bg-white">
            <Switch
              checked={!!isCompareMode}
              onChange={onOpenCompare}
              disabled={isStreaming || compareDisabled}
              size="small"
            />
            <span className="text-xs text-gray-600 whitespace-nowrap">
              {t("agent.debug.compare", "Compare")}
            </span>
          </div>
        )}
        {/* Clear history button */}
        <button
          onClick={onClear}
          disabled={isStreaming}
          className="min-w-[56px] px-4 py-1.5 rounded-md flex items-center justify-center text-sm bg-gray-200 hover:bg-gray-300 text-gray-800 whitespace-nowrap disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ border: "none" }}
        >
          {t("agent.debug.clear")}
        </button>
        {isStreaming ? (
          <button
            onClick={onStop}
            className="min-w-[56px] px-4 py-1.5 rounded-md flex items-center justify-center text-sm bg-red-500 hover:bg-red-600 text-white whitespace-nowrap"
            style={{ border: "none" }}
          >
            {t("agent.debug.stop")}
          </button>
        ) : (
          <button
            onClick={onSend}
            className="min-w-[56px] px-4 py-1.5 rounded-md flex items-center justify-center text-sm bg-blue-500 hover:bg-blue-600 text-white whitespace-nowrap"
            disabled={isInputDisabled}
            style={{ border: "none" }}
          >
            {t("agent.debug.send")}
          </button>
        )}
        </div>
      </div>
    </div>
  );
}

/**
 * Debug configuration main component
 */
export default function DebugConfig({ agentId }: DebugConfigProps) {
  const parsedAgentId =
    agentId === undefined || agentId === null || Number.isNaN(Number(agentId))
      ? undefined
      : Number(agentId);
  const { t } = useTranslation();
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [inputQuestion, setInputQuestion] = useState("");
  const [selectedModelId, setSelectedModelId] = useState<number | null>(null);
  const { availableLlmModels } = useModelList();
  const { agentInfo } = useAgentInfo(parsedAgentId);
  const editedAgent = useAgentConfigStore((state) => state.editedAgent);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const prevAgentIdRef = useRef<number | null | undefined>(undefined);
  // Maintain an independent step ID counter per Agent
  const stepIdCounter = useRef<{ current: number }>({ current: 0 });

  const [debugOptimizeOpen, setDebugOptimizeOpen] = useState(false);
  const [debugOptimizeSelected, setDebugOptimizeSelected] = useState<null | {
    userQuestion: string;
    assistantAnswer: string;
    history: Array<{ role: string; content: string }>;
  }>(null);
  const [compareOriginalPrompt, setCompareOriginalPrompt] = useState("");
  const [compareOptimizedPrompt, setCompareOptimizedPrompt] = useState("");

  const [isComparePanelOpen, setIsComparePanelOpen] = useState(false);
  const [compareLeftModelId, setCompareLeftModelId] = useState<number | null>(null);
  const [compareRightModelId, setCompareRightModelId] = useState<number | null>(null);
  const hasMultipleLlmModels = availableLlmModels.length >= 2;

  // Attachment state
  const [attachments, setAttachments] = useState<FilePreview[]>([]);
  const [fileUrls, setFileUrls] = useState<Record<string, string>>({});

  // Derive debug model selector options from search_info's model_ids,
  // resolving display names against the already-loaded model list.
  const debugModelIds = useMemo<number[]>(() => agentInfo?.model_ids ?? [], [agentInfo]);
  const debugModelNames = useMemo(() => {
    return debugModelIds.map((id: number) => {
      const model = availableLlmModels.find((m) => m.id === id);
      return model?.displayName || model?.name || String(id);
    });
  }, [debugModelIds, availableLlmModels]);
  const defaultModelId = useMemo(() => {
    const ids = debugModelIds;
    if (ids.length === 0) return null;
    return ids[0];
  }, [debugModelIds]);

  // Initialize selectedModelId when agent info becomes available
  useEffect(() => {
    if (debugModelIds.length > 0 && selectedModelId === null) {
      setSelectedModelId(defaultModelId);
    }
  }, [debugModelIds.length, defaultModelId, selectedModelId]);

  const comparePersistenceKey =
    parsedAgentId === undefined
      ? "debug-compare:anonymous"
      : `debug-compare:agent-${parsedAgentId}`;
  const comparePersistenceFallbackKeys =
    parsedAgentId === undefined ? [] : ["debug-compare:anonymous"];

  const {
    leftMessages: compareLeftMessages,
    rightMessages: compareRightMessages,
    isCompareStreaming,
    compareStreamingLeft,
    compareStreamingRight,
    runCompare,
    stopCompare,
    resetCompareState,
  } = useCompareStream({
    t,
    buildRunParams: ({ side, question, conversationId, history, minio_files }) => ({
      query: question,
      conversation_id: conversationId,
      is_set: true,
      history,
      is_debug: true,
      agent_id: parsedAgentId,
      model_id: side === "left" ? compareLeftModelId ?? undefined : compareRightModelId ?? undefined,
      minio_files,
    }),
    persistenceKey: comparePersistenceKey,
    persistenceFallbackKeys: comparePersistenceFallbackKeys,
    getHistory: () =>
      messages
        .filter((msg) => msg.isComplete !== false && msg.content?.trim())
        .map((msg) => ({ role: msg.role, content: msg.content })),
  });

  // Reset debug state when agentId changes
  useEffect(() => {
    const normalizedAgentId = parsedAgentId ?? null;
    const previousAgentId = prevAgentIdRef.current;
    prevAgentIdRef.current = normalizedAgentId;
    const hasSwitchedAgent =
      previousAgentId !== undefined &&
      previousAgentId !== null &&
      normalizedAgentId !== null &&
      previousAgentId !== normalizedAgentId;

    // Clear debug history
    setMessages([]);
    // Reset step ID counter
    stepIdCounter.current.current = 0;
    // Clear attachment state
    setAttachments([]);
    setFileUrls({});
    // Stop both frontend and backend when switching agent (debug mode)
    const hasActiveStream = isStreaming || abortControllerRef.current !== null;
    if (hasActiveStream) {
      handleStop();
    }

    // Check for cached error from previous debug session
    if (agentId !== undefined && agentId !== null && !isNaN(Number(agentId))) {
      const cachedError = getCachedDebugError(Number(agentId));
      if (cachedError) {
        // Restore the cached error as a message with a step containing the error
        const errorMessage: ChatMessageType = {
          id: Date.now().toString(),
          role: MESSAGE_ROLES.ASSISTANT,
          content: cachedError,
          timestamp: new Date(),
          isComplete: true,
          error: cachedError,
          // Add a step with the error info so TaskWindow can display it
          steps: [
            {
              id: "error-step",
              title: "Error",
              content: cachedError,
              expanded: true,
              metrics: null,
              thinking: { content: "", expanded: true },
              code: { content: "", expanded: true },
              output: { content: cachedError, expanded: true },
              contents: [
                {
                  id: "error-content",
                  type: "error" as const,
                  content: cachedError,
                  expanded: true,
                  timestamp: Date.now(),
                  subType: "error",
                },
              ],
            },
          ],
        };
        setMessages([errorMessage]);
      }
    }

    // Reset compare state only when switching to a different agent.
    // On initial mount/re-mount with the same agent, keep persisted compare history.
    if (hasSwitchedAgent) {
      setIsComparePanelOpen(false);
      stopCompare();
      resetCompareState();
    }
  }, [agentId]);

  useEffect(() => {
    if (!hasMultipleLlmModels) {
      setCompareLeftModelId(null);
      setCompareRightModelId(null);
      return;
    }

    const agentConfiguredIds = debugModelIds.filter((id) =>
      availableLlmModels.some((m) => m.id === id)
    );

    const defaultModelId =
      debugModelIds.length > 0
        ? debugModelIds[0]
        : null;
    const leftModelId =
      defaultModelId && agentConfiguredIds.includes(defaultModelId)
        ? defaultModelId
        : agentConfiguredIds[0] ?? availableLlmModels[0]?.id ?? null;
    const rightModelId =
      availableLlmModels.find((m) => m.id !== leftModelId)?.id ?? null;

    setCompareLeftModelId((prev) => {
      if (prev && agentConfiguredIds.includes(prev)) return prev;
      return leftModelId;
    });
    setCompareRightModelId((prev) => {
      if (prev && availableLlmModels.some((m) => m.id === prev) && prev !== leftModelId) {
        return prev;
      }
      return rightModelId;
    });
  }, [availableLlmModels, debugModelIds, hasMultipleLlmModels]);

  // Reset timeout timer
  const resetTimeout = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    timeoutRef.current = setTimeout(() => {
      setIsStreaming(false);
    }, 30000); // 30 seconds timeout
  };

  // Handle stop function
  const handleStop = async () => {
    // Stop agent_run immediately
    if (abortControllerRef.current) {
      try {
        abortControllerRef.current.abort(t("agent.debug.userStop"));
      } catch (error) {
        log.error(t("agent.debug.cancelError"), error);
      }
      abortControllerRef.current = null;
    }

    // Clear timeout timer
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }

    // Immediately update frontend state
    setIsStreaming(false);

    // Try to stop backend agent run for debug mode
    try {
      await conversationService.stop(-1); // Use -1 for debug mode
    } catch (error) {
      log.error(t("agent.debug.stopError"), error);
      // This is expected if no agent is running for debug mode
    }

    // Manually update messages, clear thinking state
    setMessages((prev) => {
      const newMessages = [...prev];
      const lastMsg = newMessages[newMessages.length - 1];
      if (lastMsg && lastMsg.role === MESSAGE_ROLES.ASSISTANT) {
        lastMsg.isComplete = true;
        lastMsg.thinking = undefined; // Explicitly clear thinking state
        lastMsg.content = t("agent.debug.stopped");
      }
      return newMessages;
    });
  };

  // Clear local history and reset the step counter
  const handleClearHistory = async () => {
    if (isComparePanelOpen) {
      if (isCompareStreaming) {
        stopCompare();
      }
      resetCompareState();
    } else {
      setMessages([]);
      stepIdCounter.current.current = 0;
    }
    setInputQuestion("");
    // Clear attachment state
    setAttachments([]);
    setFileUrls({});
    // Clear cached error for this agent
    if (agentId !== undefined && agentId !== null && !isNaN(Number(agentId))) {
      clearCachedDebugError(Number(agentId));
    }
  };


  // Process test question
  const handleTestQuestion = async (question: string) => {
    setIsStreaming(true);

    // Create new AbortController for this request
    abortControllerRef.current = new AbortController();

    // Upload attachments (if any) and build the minio_files payload.
    // Debug mode requests per-file descriptions via preprocessing (withDescription = true).
    const attachmentPayload = await buildMinioFilePayload(
      attachments,
      fileUrls,
      question,
      abortControllerRef.current?.signal,
      true,
      t
    );
    if (attachmentPayload.error) {
      antMessage.error(`${t("chatPreprocess.fileUploadFailed")} ${attachmentPayload.error}`);
      setIsStreaming(false);
      abortControllerRef.current = null;
      return;
    }
    const { messageAttachments, minioFiles } = attachmentPayload;

    // Add user message
    const userMessage: ChatMessageType = {
      id: Date.now().toString(),
      role: MESSAGE_ROLES.USER,
      content: question,
      timestamp: new Date(),
      attachments: messageAttachments.length > 0 ? messageAttachments : undefined,
    };

    // Add assistant message (initial state)
    const assistantMessage: ChatMessageType = {
      id: (Date.now() + 1).toString(),
      role: MESSAGE_ROLES.ASSISTANT,
      content: "",
      timestamp: new Date(),
      isComplete: false,
    };

    setMessages((prev) => [...prev, userMessage, assistantMessage]);

    // Clear attachments after adding them to the message
    setAttachments([]);
    setFileUrls({});

    // Ensure agent_id is a number
    let agentIdValue: number | undefined = undefined;
    if (agentId !== undefined && agentId !== null) {
      agentIdValue = Number(agentId);
      if (isNaN(agentIdValue)) {
        agentIdValue = undefined;
      }
    }

    try {
      // Call agent_run with AbortSignal
      const reader = await conversationService.runAgent(
        {
          query: question,
          conversation_id: -1, // Debug mode uses -1 as conversation ID
          history: messages
            .filter(msg => msg.isComplete !== false) // Only pass completed messages
            .map(msg => {
              const historyItem: any = {
                role: msg.role,
                content:
                  msg.role === MESSAGE_ROLES.ASSISTANT
                    ? msg.finalAnswer?.trim() || msg.content || ""
                    : msg.content || "",
              };
              // Include attachment info for historical messages
              if (msg.attachments && msg.attachments.length > 0) {
                historyItem.minio_files = msg.attachments.map((att) => ({
                  object_name: att.object_name || "",
                  name: att.name,
                  type: att.type,
                  size: att.size,
                  url: att.url || "",
                  presigned_url: att.presigned_url || "",
                  description: att.description || "",
                }));
              }
              return historyItem;
            }),
          is_debug: true, // Add debug mode flag
          agent_id: agentIdValue, // Use the properly parsed agent_id
          minio_files: minioFiles.length > 0 ? minioFiles : undefined,
          model_id: selectedModelId ?? undefined,
        },
        abortControllerRef.current.signal
      ); // Pass AbortSignal

      if (!reader) throw new Error(t("agent.debug.nullResponse"));

      // Process stream response
      await handleStreamResponse(
        reader,
        setMessages,
        resetTimeout,
        stepIdCounter.current,
        () => {}, // setIsSwitchedConversation - Debug mode does not need
        false, // isNewConversation - Debug mode does not need
        () => {}, // setConversationTitle - Debug mode does not need
        async () => {}, // fetchConversationList - Debug mode does not need
        -1, // currentConversationId - Debug mode uses -1
        conversationService,
        true, // isDebug: true for debug mode
        t
      );
    } catch (error) {
      // If user actively canceled, don't show error message
      const err = error as Error;
      const isUserStop =
        err.name === "AbortError" || err.message === t("agent.debug.userStop");
      if (isUserStop) {
        setMessages((prev) => {
          const newMessages = [...prev];
          const lastMsg = newMessages[newMessages.length - 1];
          if (lastMsg && lastMsg.role === MESSAGE_ROLES.ASSISTANT) {
            lastMsg.content = t("agent.debug.stopped");
            lastMsg.isComplete = true;
            lastMsg.thinking = undefined; // Explicitly clear thinking state
          }
          return newMessages;
        });
      } else {
        log.error(t("agent.debug.streamError"), error);
        const errorMessage =
          error instanceof Error
            ? error.message
            : t("agent.debug.processError");

        // Cache the error for future debug sessions
        if (agentIdValue !== undefined) {
          cacheDebugError(agentIdValue, errorMessage);
        }

        setMessages((prev) => {
          const newMessages = [...prev];
          const lastMsg = newMessages[newMessages.length - 1];
          if (lastMsg && lastMsg.role === MESSAGE_ROLES.ASSISTANT) {
            lastMsg.content = errorMessage;
            lastMsg.isComplete = true;
            lastMsg.error = errorMessage;
          }
          return newMessages;
        });
      }
    } finally {
      setIsStreaming(false);
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
      if (abortControllerRef.current) {
        abortControllerRef.current = null;
      }
    }
  };

  const handleCompare = async () => {
    const question = inputQuestion.trim();
    if (!question) return;
    if (!compareLeftModelId || !compareRightModelId) return;
    if (compareLeftModelId === compareRightModelId) return;
    setInputQuestion("");

    // Upload attachments (if any) and build the minio_files payload.
    // Compare mode skips per-file descriptions (withDescription = false).
    const attachmentPayload = await buildMinioFilePayload(
      attachments,
      fileUrls,
      question,
      undefined,
      false,
      t
    );
    if (attachmentPayload.error) {
      antMessage.error(`${t("chatPreprocess.fileUploadFailed")} ${attachmentPayload.error}`);
      return;
    }
    const { messageAttachments, minioFiles } = attachmentPayload;

    // Clear attachments after preparing them
    setAttachments([]);
    setFileUrls({});

    await runCompare(
      question,
      minioFiles.length > 0 ? minioFiles : undefined,
      messageAttachments.length > 0 ? messageAttachments : undefined
    );
  };

  const comparePanel = isComparePanelOpen ? (
    <div className="flex flex-col gap-3 h-full min-h-0">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="flex flex-col gap-1">
            <span className="text-xs text-gray-500">
              {t("agent.debug.compareDefault", "Default model")}
            </span>
            <Select
              value={compareLeftModelId ?? undefined}
              onChange={(value) => setCompareLeftModelId(value)}
              options={debugModelIds
                .map((id) => {
                  const model = availableLlmModels.find((m) => m.id === id);
                  return model
                    ? { value: model.id, label: model.displayName || model.name }
                    : null;
                })
                .filter(
                  (opt): opt is { value: number; label: string } => opt !== null
                )}
              placeholder={t("agent.debug.compareSelectModel", "Select model")}
              disabled={isCompareStreaming}
              allowClear={false}
            />
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs text-gray-500">
              {t("agent.debug.compareRight", "Right model")}
            </span>
            <Select
              value={compareRightModelId ?? undefined}
              onChange={(value) => setCompareRightModelId(value)}
              options={availableLlmModels
                .filter((model) => model.id !== compareLeftModelId)
                .map((model) => ({
                  value: model.id,
                  label: model.displayName || model.name,
                }))}
              placeholder={t("agent.debug.compareSelectModel", "Select model")}
              disabled={isCompareStreaming}
            />
          </div>
        </div>

        {isCompareStreaming && (
          <div className="flex justify-end">
            <button
              onClick={stopCompare}
              className="min-w-[72px] px-4 py-1.5 rounded-md flex items-center justify-center text-sm bg-red-500 hover:bg-red-600 text-white whitespace-nowrap"
              style={{ border: "none" }}
            >
              {t("agent.debug.stop")}
            </button>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 flex-1 min-h-0">
          <div className="flex flex-col min-h-0 border border-gray-200 rounded-md p-3 overflow-hidden">
            <div className="text-xs text-gray-500 mb-2">
              {(() => {
                const model = availableLlmModels.find((m) => m.id === compareLeftModelId);
                return model ? model.displayName || model.name : editedAgent.model || "-";
              })()}
            </div>
            <DebugMessageList
              messages={compareLeftMessages}
              isStreaming={compareStreamingLeft}
              emptyPlaceholder={t("agent.debug.compareEmpty", "No output yet")}
            />
          </div>
          <div className="flex flex-col min-h-0 border border-gray-200 rounded-md p-3 overflow-hidden">
            <div className="text-xs text-gray-500 mb-2">
              {(() => {
                const model = availableLlmModels.find((m) => m.id === compareRightModelId);
                return model ? model.displayName || model.name : "-";
              })()}
            </div>
            <DebugMessageList
              messages={compareRightMessages}
              isStreaming={compareStreamingRight}
              emptyPlaceholder={t("agent.debug.compareEmpty", "No output yet")}
            />
          </div>
        </div>
      </div>
  ) : null;

  const toggleComparePanel = () => {
    const nextOpen = !isComparePanelOpen;
    setIsComparePanelOpen(nextOpen);
    if (nextOpen) {
      if (isStreaming || abortControllerRef.current) {
        handleStop();
      }
      // Enter compare mode: clear default chat history and compare outputs
      setMessages([]);
      stepIdCounter.current.current = 0;
    } else if (isCompareStreaming) {
      stopCompare();
    }
  };

  // Handle file selection with validation
  const handleFileSelect = (files: File[]) => {
    // Check file count limit
    if (attachments.length + files.length > MAX_FILE_COUNT) {
      antMessage.error(t("chatInput.fileCountExceedsLimit", { count: MAX_FILE_COUNT }));
      return;
    }

    const newAttachments: FilePreview[] = [];

    for (const file of files) {
      // Check single file size limit
      if (file.size > MAX_FILE_SIZE) {
        antMessage.error(t("chatInput.fileSizeExceedsLimit", { name: file.name }));
        return;
      }

      const fileId = crypto.randomUUID();
      const extension = getFileExtension(file.name);

      const isImage = file.type.startsWith("image/") || chatConfig.imageExtensions.includes(extension);
      const isSupported = isSupportedFile(extension, file.type);

      if (!isSupported) {
        antMessage.error(t("chatInput.unsupportedFileType", { name: file.name }));
        return;
      }

      const previewUrl = isImage ? URL.createObjectURL(file) : undefined;

      newAttachments.push({
        id: fileId,
        file,
        type: isImage ? chatConfig.filePreviewTypes.image : chatConfig.filePreviewTypes.file,
        fileType: file.type,
        extension,
        previewUrl,
      });

      // Create local URL for non-image files
      if (!isImage) {
        const fileUrl = URL.createObjectURL(file);
        setFileUrls((prev) => ({ ...prev, [fileId]: fileUrl }));
      }
    }

    if (newAttachments.length > 0) {
      setAttachments([...attachments, ...newAttachments]);
    }
  };

  // Handle removing an attachment
  const handleRemoveAttachment = (id: string) => {
    const attachment = attachments.find((a) => a.id === id);
    if (attachment?.previewUrl) {
      URL.revokeObjectURL(attachment.previewUrl);
    }
    const fileUrl = fileUrls[id];
    if (fileUrl) {
      URL.revokeObjectURL(fileUrl);
      setFileUrls((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
    }
    setAttachments(attachments.filter((a) => a.id !== id));
  };

  // Hold the latest attachment state for the unmount-only cleanup below.
  // Kept in a ref because the cleanup effect has `[]` deps and would otherwise
  // capture a stale (initial) snapshot of attachments/fileUrls.
  const attachmentStateRef = useRef({ attachments, fileUrls });
  useEffect(() => {
    attachmentStateRef.current = { attachments, fileUrls };
  });

  // Revoke any remaining object URLs when the component unmounts.
  // NOTE: deps are intentionally `[]`. With `[attachments, fileUrls]` here, React
  // would run the cleanup with the *previous* closure on every state change,
  // revoking URLs of attachments that are still in the list and breaking their
  // previews. Per-attachment revocation on removal is handled in handleRemoveAttachment;
  // this effect only acts as a teardown safety net for anything still attached at unmount.
  useEffect(() => {
    return () => {
      cleanupAttachmentUrls(
        attachmentStateRef.current.attachments,
        attachmentStateRef.current.fileUrls
      );
    };
  }, []);

  const handleSend = () => {
    if (!inputQuestion.trim()) return;
    if (isComparePanelOpen) {
      handleCompare();
    } else {
      handleTestQuestion(inputQuestion);
      setInputQuestion("");
    }
  };

  const handleOpenOptimize = (params: {
    userQuestion: string;
    assistantAnswer: string;
    history: Array<{ role: string; content: string }>;
  }) => {
    if (!parsedAgentId) return;
    if (!editedAgent?.model_ids || editedAgent.model_ids.length === 0) return;

    const duty = (editedAgent?.duty_prompt || "").trim();
    const constraint = (editedAgent?.constraint_prompt || "").trim();
    const fewShots = (editedAgent?.few_shots_prompt || "").trim();

    const originalFullPrompt = [
      "# 智能体角色",
      duty,
      "",
      "# 使用要求",
      constraint,
      "",
      "# 示例",
      fewShots,
    ]
      .filter((part) => part !== undefined)
      .join("\n")
      .trim();

    setCompareOriginalPrompt(originalFullPrompt);
    setCompareOptimizedPrompt("");

    setDebugOptimizeSelected(params);
    setDebugOptimizeOpen(true);
  };

  const handleOptimized = (params: {
    originalFullPrompt: string;
    optimizedFullPrompt: string;
  }) => {
    setCompareOriginalPrompt(params.originalFullPrompt || "");
    setCompareOptimizedPrompt(params.optimizedFullPrompt || "");
  };

  const handleApplyOptimizedPrompt = (optimizedFullPrompt?: string) => {
    const optimized = (optimizedFullPrompt || compareOptimizedPrompt || "").trim();
    if (!optimized) {
      return;
    }

    const normalized = optimized
      .replace(/\r\n/g, "\n")
      .replace(/^#\s*智能体角色\s*$/gm, "# Duty")
      .replace(/^#\s*使用要求\s*$/gm, "# Constraint")
      .replace(/^#\s*示例\s*$/gm, "# FewShots");

    const pickSection = (header: "Duty" | "Constraint" | "FewShots"): string => {
      const headerRegex = new RegExp(`^#\\s*${header}\\s*$`, "gm");
      const matches = [...normalized.matchAll(headerRegex)];
      const current = matches[0];
      if (!current) return "";

      const start = current.index + current[0].length;
      const rest = normalized.slice(start);
      const nextHeaderMatch = rest.match(/^#\s*(Duty|Constraint|FewShots)\s*$/m);
      const end = nextHeaderMatch?.index ?? rest.length;
      return rest.slice(0, end).trim();
    };

    const duty = pickSection("Duty");
    const constraint = pickSection("Constraint");
    const fewShots = pickSection("FewShots");

    const updateAgentConfig = useAgentConfigStore.getState().updateAgentConfig;

    updateAgentConfig({
      ...(duty ? { duty_prompt: duty } : {}),
      ...(constraint ? { constraint_prompt: constraint } : {}),
      ...(fewShots ? { few_shots_prompt: fewShots } : {}),
    });
    // Close optimize modal after applying.
    setDebugOptimizeOpen(false);
    setDebugOptimizeSelected(null);
    setCompareOriginalPrompt("");
    setCompareOptimizedPrompt("");
  };

  return (
    <div className="w-full h-full bg-white">
      <DebugOptimizeModal
        open={debugOptimizeOpen}
        agentId={parsedAgentId ?? 0}
        modelId={editedAgent?.model_ids?.[0] ?? 0}
        userQuestion={debugOptimizeSelected?.userQuestion || ""}
        assistantAnswer={debugOptimizeSelected?.assistantAnswer || ""}
        history={debugOptimizeSelected?.history || []}
        initialOriginalFullPrompt={compareOriginalPrompt || ""}
        onCancel={() => {
          setDebugOptimizeOpen(false);
          setDebugOptimizeSelected(null);
          setCompareOriginalPrompt("");
          setCompareOptimizedPrompt("");
        }}
        onOptimized={handleOptimized}
        onApply={(optimizedFullPrompt) => {
          setCompareOptimizedPrompt(optimizedFullPrompt || "");
          handleApplyOptimizedPrompt(optimizedFullPrompt);
        }}
      />

      <AgentDebugging
        key={agentId} // Re-render when agentId changes to ensure state resets
        onStop={handleStop}
        onClear={handleClearHistory}
        inputQuestion={inputQuestion}
        onInputChange={setInputQuestion}
        onSend={handleSend}
        isStreaming={isStreaming}
        isCompareStreaming={isCompareStreaming}
        messages={messages}
        onOptimizeReply={handleOpenOptimize}
        comparePanel={comparePanel}
        showCompare={hasMultipleLlmModels}
        onOpenCompare={toggleComparePanel}
        compareDisabled={isCompareStreaming}
        isCompareMode={isComparePanelOpen}
        attachments={attachments}
        onFileSelect={handleFileSelect}
        onRemoveAttachment={handleRemoveAttachment}
        modelIds={debugModelIds}
        modelNames={debugModelNames}
        selectedModelId={selectedModelId}
        onModelSelect={setSelectedModelId}
      />
    </div>
  );
}
