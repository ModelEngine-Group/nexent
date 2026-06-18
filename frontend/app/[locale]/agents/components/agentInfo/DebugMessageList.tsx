"use client";

import { ChatStreamFinalMessage } from "@/app/chat/streaming/chatStreamFinalMessage";
import { TaskWindow } from "@/app/chat/streaming/taskWindow";
import { transformMessagesToTaskMessages } from "@/app/chat/streaming/messageTransformer";
import { MESSAGE_ROLES } from "@/const/chatConfig";
import { ChatMessageType, TaskMessageType } from "@/types/chat";

interface DebugMessageListProps {
  messages: ChatMessageType[];
  isStreaming: boolean;
  emptyPlaceholder?: string;
}

export default function DebugMessageList({
  messages,
  isStreaming,
  emptyPlaceholder,
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

  return (
    <div className="flex flex-col gap-3 h-full overflow-y-auto custom-scrollbar">
      {messages.map((message, index) => {
        const currentTaskMessages =
          message.role === MESSAGE_ROLES.ASSISTANT
            ? processMessageSteps(message)
            : [];

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
  );
}
