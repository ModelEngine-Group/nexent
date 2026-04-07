"use client";

import { useState, useRef, useEffect, type Dispatch, type SetStateAction } from "react";
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
  const compareTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const compareAbortControllersRef = useRef<{
    left: AbortController | null;
    right: AbortController | null;
  }>({ left: null, right: null });
  const compareConversationIdsRef = useRef<{
    left: number | null;
    right: number | null;
  }>({ left: null, right: null });
  const compareStepIdCountersRef = useRef<{
    left: { current: number };
    right: { current: number };
  }>({
    left: { current: 0 },
    right: { current: 0 },
  });
  const compareInFlightRef = useRef(0);
  const [isComparePanelOpen, setIsComparePanelOpen] = useState(false);
  const [compareLeftModelId, setCompareLeftModelId] = useState<number | null>(null);
  const [compareRightModelId, setCompareRightModelId] = useState<number | null>(null);
  const [compareLeftMessages, setCompareLeftMessages] = useState<ChatMessageType[]>([]);
  const [compareRightMessages, setCompareRightMessages] = useState<ChatMessageType[]>([]);
  const [isCompareStreaming, setIsCompareStreaming] = useState(false);
  const [compareStreamingLeft, setCompareStreamingLeft] = useState(false);
  const [compareStreamingRight, setCompareStreamingRight] = useState(false);
  const hasMultipleLlmModels = availableLlmModels.length >= 2;

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
    setCompareLeftMessages([]);
    setCompareRightMessages([]);
    compareStepIdCountersRef.current.left.current = 0;
    compareStepIdCountersRef.current.right.current = 0;
    setIsComparePanelOpen(false);
    handleCompareStop();
  }, [agentId]);

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

  const resetCompareTimeout = () => {
    if (compareTimeoutRef.current) {
      clearTimeout(compareTimeoutRef.current);
    }
    compareTimeoutRef.current = setTimeout(() => {
      setIsCompareStreaming(false);
    }, 30000);
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

  const markCompareStopped = (setSideMessages: (value: (prev: ChatMessageType[]) => ChatMessageType[]) => void) => {
    setSideMessages((prev) => {
      const newMessages = [...prev];
      const lastMsg = newMessages[newMessages.length - 1];
      if (lastMsg && lastMsg.role === MESSAGE_ROLES.ASSISTANT) {
        lastMsg.isComplete = true;
        lastMsg.thinking = undefined;
        lastMsg.content = t("agent.debug.stopped");
      }
      return newMessages;
    });
  };

  const handleCompareStop = async () => {
    if (compareAbortControllersRef.current.left) {
      try {
        compareAbortControllersRef.current.left.abort(t("agent.debug.userStop"));
      } catch (error) {
        log.error(t("agent.debug.cancelError"), error);
      }
    }
    if (compareAbortControllersRef.current.right) {
      try {
        compareAbortControllersRef.current.right.abort(t("agent.debug.userStop"));
      } catch (error) {
        log.error(t("agent.debug.cancelError"), error);
      }
    }

    compareAbortControllersRef.current = { left: null, right: null };

    if (compareTimeoutRef.current) {
      clearTimeout(compareTimeoutRef.current);
      compareTimeoutRef.current = null;
    }

    setIsCompareStreaming(false);
    setCompareStreamingLeft(false);
    setCompareStreamingRight(false);
    markCompareStopped(setCompareLeftMessages);
    markCompareStopped(setCompareRightMessages);

    const { left, right } = compareConversationIdsRef.current;
    compareConversationIdsRef.current = { left: null, right: null };

    if (left != null) {
      try {
        await conversationService.stop(left);
      } catch (error) {
        log.error(t("agent.debug.stopError"), error);
      }
    }
    if (right != null) {
      try {
        await conversationService.stop(right);
      } catch (error) {
        log.error(t("agent.debug.stopError"), error);
      }
    }
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
          is_set: true,
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
      if (err.name === "AbortError") {
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

  const runCompareStream = async (params: {
    modelId: number;
    conversationId: number;
    controller: AbortController;
    setSideMessages: Dispatch<SetStateAction<ChatMessageType[]>>;
    stepIdCounterRef: { current: number };
    history: Array<{ role: string; content: string }>;
    question: string;
    agentIdValue?: number;
    onStreamEnd: () => void;
  }) => {
    try {
      const reader = await conversationService.runAgent(
        {
          query: params.question,
          conversation_id: params.conversationId,
          is_set: true,
          history: params.history,
          is_debug: true,
          agent_id: params.agentIdValue,
          model_id: params.modelId,
        },
        params.controller.signal
      );

      if (!reader) throw new Error(t("agent.debug.nullResponse"));

      await handleStreamResponse(
        reader,
        params.setSideMessages,
        resetCompareTimeout,
        params.stepIdCounterRef,
        () => {}, // setIsSwitchedConversation - Debug mode does not need
        false, // isNewConversation - Debug mode does not need
        () => {}, // setConversationTitle - Debug mode does not need
        async () => {}, // fetchConversationList - Debug mode does not need
        params.conversationId,
        conversationService,
        true, // isDebug: true for debug mode
        t
      );
    } catch (error) {
      const err = error as Error;
      if (err.name === "AbortError") {
        markCompareStopped(params.setSideMessages);
      } else {
        log.error(t("agent.debug.streamError"), error);
        const errorMessage =
          error instanceof Error
            ? error.message
            : t("agent.debug.processError");
        params.setSideMessages((prev) => {
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
      compareInFlightRef.current -= 1;
      if (compareInFlightRef.current <= 0) {
        setIsCompareStreaming(false);
      }
      params.onStreamEnd();
    }
  };

  const handleCompare = async () => {
    const question = inputQuestion.trim();
    if (!question) return;
    if (!compareLeftModelId || !compareRightModelId) return;
    if (compareLeftModelId === compareRightModelId) return;

    setIsCompareStreaming(true);
    setCompareStreamingLeft(true);
    setCompareStreamingRight(true);
    compareInFlightRef.current = 2;
    compareStepIdCountersRef.current.left.current = 0;
    compareStepIdCountersRef.current.right.current = 0;
    setInputQuestion("");

    const leftUserMessage: ChatMessageType = {
      id: `${Date.now()}-left-user`,
      role: MESSAGE_ROLES.USER,
      content: question,
      timestamp: new Date(),
    };
    const rightUserMessage: ChatMessageType = {
      id: `${Date.now()}-right-user`,
      role: MESSAGE_ROLES.USER,
      content: question,
      timestamp: new Date(),
    };

    const leftAssistantMessage: ChatMessageType = {
      id: `${Date.now()}-left-assistant`,
      role: MESSAGE_ROLES.ASSISTANT,
      content: "",
      timestamp: new Date(),
      isComplete: false,
    };
    const rightAssistantMessage: ChatMessageType = {
      id: `${Date.now()}-right-assistant`,
      role: MESSAGE_ROLES.ASSISTANT,
      content: "",
      timestamp: new Date(),
      isComplete: false,
    };

    setCompareLeftMessages([leftUserMessage, leftAssistantMessage]);
    setCompareRightMessages([rightUserMessage, rightAssistantMessage]);

    let agentIdValue: number | undefined = undefined;
    if (agentId !== undefined && agentId !== null) {
      agentIdValue = Number(agentId);
      if (isNaN(agentIdValue)) {
        agentIdValue = undefined;
      }
    }

    const baseId = -Math.abs(Date.now());
    const leftConversationId = baseId;
    const rightConversationId = baseId - 1;
    compareConversationIdsRef.current = {
      left: leftConversationId,
      right: rightConversationId,
    };

    const history = messages
      .filter((msg) => msg.isComplete !== false && msg.content?.trim())
      .map((msg) => ({ role: msg.role, content: msg.content }));

    const leftController = new AbortController();
    const rightController = new AbortController();
    compareAbortControllersRef.current = {
      left: leftController,
      right: rightController,
    };

    await Promise.allSettled([
      runCompareStream({
        modelId: compareLeftModelId,
        conversationId: leftConversationId,
        controller: leftController,
        setSideMessages: setCompareLeftMessages,
        stepIdCounterRef: compareStepIdCountersRef.current.left,
        history,
        question,
        agentIdValue,
        onStreamEnd: () => setCompareStreamingLeft(false),
      }),
      runCompareStream({
        modelId: compareRightModelId,
        conversationId: rightConversationId,
        controller: rightController,
        setSideMessages: setCompareRightMessages,
        stepIdCounterRef: compareStepIdCountersRef.current.right,
        history,
        question,
        agentIdValue,
        onStreamEnd: () => setCompareStreamingRight(false),
      }),
    ]);

    compareAbortControllersRef.current = { left: null, right: null };
    if (compareTimeoutRef.current) {
      clearTimeout(compareTimeoutRef.current);
      compareTimeoutRef.current = null;
    }
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
              onClick={handleCompareStop}
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
      setCompareLeftMessages([]);
      setCompareRightMessages([]);
      compareStepIdCountersRef.current.left.current = 0;
      compareStepIdCountersRef.current.right.current = 0;
      setIsCompareStreaming(false);
      setCompareStreamingLeft(false);
      setCompareStreamingRight(false);
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
