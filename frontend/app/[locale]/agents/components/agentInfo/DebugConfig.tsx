"use client";

import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";

import { Input, Select, Switch } from "antd";

import { conversationService } from "@/services/conversationService";
import { ChatMessageType } from "@/types/chat";
import { handleStreamResponse } from "@/app/chat/streaming/chatStreamHandler";
import { MESSAGE_ROLES } from "@/const/chatConfig";
import log from "@/lib/logger";
import {
  getCachedDebugError,
  cacheDebugError,
  clearCachedDebugError,
} from "@/lib/agentDebugErrorCache";
import { useModelList } from "@/hooks/model/useModelList";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import DebugMessageList from "./DebugMessageList";
import { useCompareStream } from "./useCompareStream";

// Agent debugging component Props interface
interface AgentDebuggingProps {
  onStop: () => void;
  onClear: () => void;
  inputQuestion: string;
  onInputChange: (value: string) => void;
  onSend: () => void;
  isStreaming: boolean;
  messages: ChatMessageType[];
  comparePanel?: React.ReactNode;
  showCompare?: boolean;
  onOpenCompare?: () => void;
  compareDisabled?: boolean;
  isCompareMode?: boolean;
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
  messages,
  comparePanel,
  showCompare,
  onOpenCompare,
  compareDisabled,
  isCompareMode,
}: AgentDebuggingProps) {
  const { t } = useTranslation();

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
            <DebugMessageList messages={messages} isStreaming={isStreaming} />
          </div>
        )}

        <div className="flex items-center gap-2 mt-auto pt-4">
        <Input
          value={inputQuestion}
          onChange={(e) => onInputChange(e.target.value)}
          placeholder={t("agent.debug.placeholder")}
          onPressEnter={onSend}
          disabled={isStreaming}
        />
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
  const { t } = useTranslation();
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [inputQuestion, setInputQuestion] = useState("");
  const { availableLlmModels } = useModelList();
  const editedAgent = useAgentConfigStore((state) => state.editedAgent);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  // Maintain an independent step ID counter per Agent
  const stepIdCounter = useRef<{ current: number }>({ current: 0 });
  const [isComparePanelOpen, setIsComparePanelOpen] = useState(false);
  const [compareLeftModelId, setCompareLeftModelId] = useState<number | null>(null);
  const [compareRightModelId, setCompareRightModelId] = useState<number | null>(null);
  const hasMultipleLlmModels = availableLlmModels.length >= 2;

  const parsedAgentId =
    agentId === undefined || agentId === null || Number.isNaN(Number(agentId))
      ? undefined
      : Number(agentId);

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
    buildRunParams: ({ side, question, conversationId, history }) => ({
      query: question,
      conversation_id: conversationId,
      is_set: true,
      history,
      is_debug: true,
      agent_id: parsedAgentId,
      model_id: side === "left" ? compareLeftModelId ?? undefined : compareRightModelId ?? undefined,
    }),
    getHistory: () =>
      messages
        .filter((msg) => msg.isComplete !== false && msg.content?.trim())
        .map((msg) => ({ role: msg.role, content: msg.content })),
  });

  // Reset debug state when agentId changes
  useEffect(() => {
    // Clear debug history
    setMessages([]);
    // Reset step ID counter
    stepIdCounter.current.current = 0;
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
              metrics: "",
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

    // Reset compare state when switching agents
    setIsComparePanelOpen(false);
    stopCompare();
    resetCompareState();
  }, [agentId, resetCompareState, stopCompare]);

  useEffect(() => {
    if (!hasMultipleLlmModels) {
      setCompareLeftModelId(null);
      setCompareRightModelId(null);
      return;
    }

    const defaultModelId =
      editedAgent.model_id && editedAgent.model_id !== 0
        ? editedAgent.model_id
        : null;
    const fallbackLeftModelId = availableLlmModels[0]?.id ?? null;
    const leftModelId =
      defaultModelId && availableLlmModels.some((m) => m.id === defaultModelId)
        ? defaultModelId
        : fallbackLeftModelId;
    const rightModelId =
      availableLlmModels.find((m) => m.id !== leftModelId)?.id ?? null;

    setCompareLeftModelId((prev) => {
      if (prev && availableLlmModels.some((m) => m.id === prev)) return prev;
      return leftModelId;
    });
    setCompareRightModelId((prev) => {
      if (prev && availableLlmModels.some((m) => m.id === prev) && prev !== leftModelId) {
        return prev;
      }
      return rightModelId;
    });
  }, [availableLlmModels, hasMultipleLlmModels, editedAgent.model_id]);

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
    setMessages([]);
    stepIdCounter.current.current = 0;
    setInputQuestion("");
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

    // Add user message
    const userMessage: ChatMessageType = {
      id: Date.now().toString(),
      role: MESSAGE_ROLES.USER,
      content: question,
      timestamp: new Date(),
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
            .map(msg => ({
              role: msg.role,
              content: msg.content
            })),
          is_debug: true, // Add debug mode flag
          agent_id: agentIdValue, // Use the properly parsed agent_id
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
    await runCompare(question);
  };

  const comparePanel = isComparePanelOpen ? (
    <div className="flex flex-col gap-3 h-full min-h-0">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="flex flex-col gap-1">
            <span className="text-xs text-gray-500">
              {t("agent.debug.compareDefault", "Default model")}
            </span>
            <div className="px-3 py-2 border border-gray-200 rounded-md text-sm bg-gray-50 text-gray-700">
              {(() => {
                const model = availableLlmModels.find((m) => m.id === compareLeftModelId);
                return model ? model.displayName || model.name : editedAgent.model || "-";
              })()}
            </div>
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
      if (isCompareStreaming) {
        stopCompare();
      }
      resetCompareState();
    }
  };

  const handleSend = () => {
    if (!inputQuestion.trim()) return;
    if (isComparePanelOpen) {
      handleCompare();
    } else {
      handleTestQuestion(inputQuestion);
      setInputQuestion("");
    }
  };

  return (
    <div className="w-full h-full bg-white">
      <AgentDebugging
        key={agentId} // Re-render when agentId changes to ensure state resets
        onStop={handleStop}
        onClear={handleClearHistory}
        inputQuestion={inputQuestion}
        onInputChange={setInputQuestion}
        onSend={handleSend}
        isStreaming={isStreaming}
        messages={messages}
        comparePanel={comparePanel}
        showCompare={hasMultipleLlmModels}
        onOpenCompare={toggleComparePanel}
        compareDisabled={isCompareStreaming}
        isCompareMode={isComparePanelOpen}
      />
    </div>
  );
}
