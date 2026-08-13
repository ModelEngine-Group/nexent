"use client";

import { ChatStreamFinalMessage } from "@/app/chat/streaming/chatStreamFinalMessage";
import { TaskWindow } from "@/app/chat/streaming/taskWindow";
import { transformMessagesToTaskMessages } from "@/app/chat/streaming/messageTransformer";
import { MESSAGE_ROLES } from "@/const/chatConfig";
import { ChatMessageType, TaskMessageType } from "@/types/chat";
import { Button, Tooltip } from "antd";
import { Sparkles } from "lucide-react";

interface DebugMessageListProps {
  messages: ChatMessageType[];
  isStreaming: boolean;
  emptyPlaceholder?: string;
  onOptimizeReply?: (params: {
    userQuestion: string;
    assistantAnswer: string;
    history: Array<{ role: string; content: string }>;
  }) => void;
}

export default function DebugMessageList({
  messages,
  isStreaming,
  emptyPlaceholder,
  onOptimizeReply,
}: DebugMessageListProps) {
  const processMessageSteps = (message: ChatMessageType): TaskMessageType[] => {
    if (!message.steps || message.steps.length === 0) return [];

    const { taskMessages } = transformMessagesToTaskMessages([message], {
      includeCode: true,
    });

    return taskMessages;
  };

  if (!messages.length && emptyPlaceholder) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-gray-400">
        {emptyPlaceholder}
      </div>
    );
  }

  const buildHistory = () =>
    messages
      .filter((msg) => msg.isComplete !== false && msg.content?.trim())
      .map((msg) => ({
        role: msg.role,
        content:
          msg.role === MESSAGE_ROLES.ASSISTANT
            ? msg.finalAnswer?.trim() || msg.content || ""
            : msg.content || "",
      }));

  const onOptimizeClick = (assistantIndex: number) => {
    if (!onOptimizeReply) return;

    const assistantMsg = messages[assistantIndex];
    if (!assistantMsg) return;

    const assistantAnswer = assistantMsg.finalAnswer?.trim() || assistantMsg.content || "";
    if (!assistantAnswer.trim()) return;

    const userMsg = [...messages]
      .slice(0, assistantIndex)
      .reverse()
      .find((m) => m.role === MESSAGE_ROLES.USER);

    const userQuestion = userMsg?.content || "";

    onOptimizeReply({
      userQuestion,
      assistantAnswer,
      history: buildHistory(),
    });
  };

  return (
    <div className="flex flex-col gap-3 h-full overflow-y-auto custom-scrollbar">
      {messages.map((message, index) => {
        const currentTaskMessages =
          message.role === MESSAGE_ROLES.ASSISTANT
            ? processMessageSteps(message)
            : [];

        const isLastStreamingAssistant =
          isStreaming &&
          index === messages.length - 1 &&
          message.role === MESSAGE_ROLES.ASSISTANT;

        const canOptimize =
          Boolean(onOptimizeReply) &&
          message.role === MESSAGE_ROLES.ASSISTANT &&
          message.isComplete !== false &&
          !isLastStreamingAssistant &&
          Boolean((message.finalAnswer || message.content || "").trim());

        return (
          <div key={message.id || index} className="flex flex-col gap-2">
            {message.role === MESSAGE_ROLES.USER && (
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

            {message.role === MESSAGE_ROLES.ASSISTANT &&
              currentTaskMessages.length > 0 && (
                <TaskWindow
                  key={message.id || `task-${index}`}
                  messages={currentTaskMessages}
                  isStreaming={isStreaming && index === messages.length - 1}
                  defaultExpanded={true}
                />
              )}

            {message.role === MESSAGE_ROLES.ASSISTANT && (
              <div className="relative">
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

                {canOptimize && (
                  <div className="mt-1 flex justify-start">
                    <Tooltip title="优化" placement="top">
                      <Button
                        type="text"
                        size="small"
                        onClick={() => onOptimizeClick(index)}
                        icon={<Sparkles size={14} />}
                        className="prompt-toolbar-button"
                        style={{
                          color: "#475569",
                          width: 24,
                          minWidth: 24,
                          height: 24,
                          borderRadius: 9999,
                        }}
                      />
                    </Tooltip>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
