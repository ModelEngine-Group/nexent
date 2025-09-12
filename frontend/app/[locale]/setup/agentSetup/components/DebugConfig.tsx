"use client";

import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";

import { Input } from "antd";

import { conversationService } from "@/services/conversationService";
import { ChatMessageType, TaskMessageType } from "@/types/chat";
import { handleStreamResponse } from "@/app/chat/streaming/chatStreamHandler";
import { ChatStreamFinalMessage } from "@/app/chat/streaming/chatStreamFinalMessage";
import { TaskWindow } from "@/app/chat/streaming/taskWindow";
import { ROLE_ASSISTANT } from "@/const/agentConfig";
import log from "@/lib/logger";

// Agent debugging component Props interface
interface AgentDebuggingProps {
  onAskQuestion: (question: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  messages: ChatMessageType[];
}

// Main component Props interface
interface DebugConfigProps {
  agentId?: number; // Make agentId an optional prop
}

/**
 * Agent debugging component
 */
function AgentDebugging({
  onAskQuestion,
  onStop,
  isStreaming,
  messages,
}: AgentDebuggingProps) {
  const { t } = useTranslation();
  const [inputQuestion, setInputQuestion] = useState("");

  const handleSend = async () => {
    if (!inputQuestion.trim()) return;

    try {
      onAskQuestion(inputQuestion);
      setInputQuestion("");
    } catch (error) {
      log.error(t("agent.error.loadTools"), error);
    }
  };

  // Process the step content of the message
  const processMessageSteps = (message: ChatMessageType): TaskMessageType[] => {
    if (!message.steps || message.steps.length === 0) return [];

    const taskMsgs: TaskMessageType[] = [];
    message.steps.forEach((step) => {
      // Process step.contents
      if (step.contents && step.contents.length > 0) {
        step.contents.forEach((content) => {
          taskMsgs.push({
            id: content.id,
            role: ROLE_ASSISTANT,
            content: content.content,
            timestamp: new Date(),
            type: content.type,
            // Preserve subType so TaskWindow can style deep thinking text
            subType: content.subType as any,
          } as any);
        });
      }

      // Process step.thinking
      if (step.thinking && step.thinking.content) {
        taskMsgs.push({
          id: `thinking-${step.id}`,
          role: ROLE_ASSISTANT,
          content: step.thinking.content,
          timestamp: new Date(),
          type: "model_output_thinking",
        });
      }

      // Process step.code
      if (step.code && step.code.content) {
        taskMsgs.push({
          id: `code-${step.id}`,
          role: ROLE_ASSISTANT,
          content: step.code.content,
          timestamp: new Date(),
          type: "model_output_code",
        });
      }

      // Process step.output
      if (step.output && step.output.content) {
        taskMsgs.push({
          id: `output-${step.id}`,
          role: ROLE_ASSISTANT,
          content: step.output.content,
          timestamp: new Date(),
          type: "tool",
        });
      }
    });

    return taskMsgs;
  };

  return (
    <div className="flex flex-col h-full p-4">
      <div className="flex flex-col gap-4 flex-grow overflow-hidden">
        {/* Message display area */}
        <div className="flex flex-col gap-3 h-full overflow-y-auto custom-scrollbar">
          {messages.map((message, index) => {
            // Process the task content of the current message
            const currentTaskMessages =
              message.role === ROLE_ASSISTANT
                ? processMessageSteps(message)
                : [];

            return (
              <div key={message.id || index} className="flex flex-col gap-2">
                {/* User message */}
                {message.role === "user" && (
                  <ChatStreamFinalMessage
                    message={message}
                    onSelectMessage={() => {}}
                    isSelected={false}
                    searchResultsCount={message.searchResults?.length || 0}
                    imagesCount={message.images?.length || 0}
                    onImageClick={() => {}}
                    onOpinionChange={() => {}}
                    hideButtons={true}
                  />
                )}

                {/* Assistant message task window */}
                {message.role === ROLE_ASSISTANT &&
                  currentTaskMessages.length > 0 && (
                    <TaskWindow
                      messages={currentTaskMessages}
                      isStreaming={isStreaming && index === messages.length - 1}
                    />
                  )}

                {/* Assistant message final answer */}
                {message.role === ROLE_ASSISTANT && (
                  <ChatStreamFinalMessage
                    message={message}
                    onSelectMessage={() => {}}
                    isSelected={false}
                    searchResultsCount={message.searchResults?.length || 0}
                    imagesCount={message.images?.length || 0}
                    onImageClick={() => {}}
                    onOpinionChange={() => {}}
                    hideButtons={true}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div className="flex gap-2 mt-4">
        <Input
          value={inputQuestion}
          onChange={(e) => setInputQuestion(e.target.value)}
          placeholder={t("agent.debug.placeholder")}
          onPressEnter={handleSend}
          disabled={isStreaming}
        />
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
            onClick={handleSend}
            className="min-w-[56px] px-4 py-1.5 rounded-md flex items-center justify-center text-sm bg-blue-500 hover:bg-blue-600 text-white whitespace-nowrap"
            style={{ border: "none" }}
          >
            {t("agent.debug.send")}
          </button>
        )}
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
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  // Maintain an independent step ID counter per Agent
  const stepIdCounter = useRef<{ current: number }>({ current: 0 });

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
  }, [agentId]);

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
      if (lastMsg && lastMsg.role === ROLE_ASSISTANT) {
        lastMsg.isComplete = true;
        lastMsg.thinking = undefined; // Explicitly clear thinking state
        lastMsg.content = t("agent.debug.stopped");
      }
      return newMessages;
    });
  };

  // Process test question
  const handleTestQuestion = async (question: string) => {
    setIsStreaming(true);

    // Create new AbortController for this request
    abortControllerRef.current = new AbortController();

    // Add user message
    const userMessage: ChatMessageType = {
      id: Date.now().toString(),
      role: "user",
      content: question,
      timestamp: new Date(),
    };

    // Add assistant message (initial state)
    const assistantMessage: ChatMessageType = {
      id: (Date.now() + 1).toString(),
      role: ROLE_ASSISTANT,
      content: "",
      timestamp: new Date(),
      isComplete: false,
    };

    setMessages([userMessage, assistantMessage]);

    try {
      // Ensure agent_id is a number
      let agentIdValue = undefined;
      if (agentId !== undefined && agentId !== null) {
        agentIdValue = Number(agentId);
        if (isNaN(agentIdValue)) {
          agentIdValue = undefined;
        }
      }

      // Call agent_run with AbortSignal
      const reader = await conversationService.runAgent(
        {
          query: question,
          conversation_id: -1, // Debug mode uses -1 as conversation ID
          is_set: true,
          history: [],
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
          if (lastMsg && lastMsg.role === ROLE_ASSISTANT) {
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

        setMessages((prev) => {
          const newMessages = [...prev];
          const lastMsg = newMessages[newMessages.length - 1];
          if (lastMsg && lastMsg.role === ROLE_ASSISTANT) {
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

  return (
    <div className="w-full h-full bg-white">
      <AgentDebugging
        key={agentId} // Re-render when agentId changes to ensure state resets
        onAskQuestion={handleTestQuestion}
        onStop={handleStop}
        isStreaming={isStreaming}
        messages={messages}
      />
    </div>
  );
}
