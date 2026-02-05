import { chatConfig, MESSAGE_ROLES } from "@/const/chatConfig";
import { ChatMessageType, TaskMessageType } from "@/types/chat";

/**
 * Transform chat messages to task messages for TaskWindow rendering
 * @param messages - Array of chat messages to transform
 * @param options - Configuration options
 * @param options.includeCode - Whether to include step.code as separate task messages (for debug mode)
 * @returns Array of task messages grouped by user message ID
 */
export function transformMessagesToTaskMessages(
  messages: ChatMessageType[],
  options: {
    includeCode?: boolean;
  } = {}
): {
  taskMessages: TaskMessageType[];
  conversationGroups: Map<string, TaskMessageType[]>;
} {
  const { includeCode = false } = options;
  const taskMsgs: TaskMessageType[] = [];
  const conversationGroups = new Map<string, TaskMessageType[]>();
  const truncationBuffer = new Map<string, TaskMessageType[]>();
  const processedTruncationIds = new Set<string>();

  // First preprocess, find all user message IDs and initialize task groups
  messages.forEach((message) => {
    if (message.role === MESSAGE_ROLES.USER && message.id) {
      conversationGroups.set(message.id, []);
      truncationBuffer.set(message.id, []);
    }
  });

  let currentUserMsgId: string | null = null;

  // Process all messages
  messages.forEach((message) => {
    // User messages - record the ID for associating subsequent tasks
    if (message.role === MESSAGE_ROLES.USER && message.id) {
      currentUserMsgId = message.id;
    }
    // Assistant messages - extract task messages from steps
    else if (message.role === MESSAGE_ROLES.ASSISTANT && message.steps && message.steps.length > 0) {
      message.steps.forEach((step) => {
        // Process step.contents
        if (step.contents && step.contents.length > 0) {
          step.contents.forEach((content: any) => {
            const taskMsg: TaskMessageType = {
              id: content.id,
              role: MESSAGE_ROLES.ASSISTANT,
              content: content.content,
              timestamp: new Date(),
              type: content.type,
              subType: content.subType,
              // For preprocess messages, include the full contents array for TaskWindow
              // For search_content_placeholder messages, include search results from message level
              _messageContainer: 
                content.type === chatConfig.contentTypes.PREPROCESS 
                  ? { contents: step.contents }
                  : content.type === chatConfig.messageTypes.SEARCH_CONTENT_PLACEHOLDER && message.searchResults
                    ? { search: message.searchResults }
                    : undefined,
            } as any;

            // Handle truncation messages specially - buffer them instead of adding immediately
            if (content.type === "truncation") {
              const truncationId = `${content.filename || 'unknown'}_${content.message || ''}_${currentUserMsgId || 'no_user'}`;
              if (!processedTruncationIds.has(truncationId) && currentUserMsgId && truncationBuffer.has(currentUserMsgId)) {
                const buffer = truncationBuffer.get(currentUserMsgId) || [];
                buffer.push(taskMsg);
                truncationBuffer.set(currentUserMsgId, buffer);
                processedTruncationIds.add(truncationId);
              }
            } else {
              // For non-truncation messages, add them immediately
              taskMsgs.push(taskMsg);

              // If there is a related user message, add it to the corresponding task group
              if (currentUserMsgId && conversationGroups.has(currentUserMsgId)) {
                const tasks = conversationGroups.get(currentUserMsgId) || [];
                tasks.push(taskMsg);
                conversationGroups.set(currentUserMsgId, tasks);
              }
            }
          });
        }

        // Process step.thinking (if it exists)
        if (step.thinking && step.thinking.content) {
          const taskMsg: TaskMessageType = {
            id: `thinking-${step.id}`,
            role: MESSAGE_ROLES.ASSISTANT,
            content: step.thinking.content,
            timestamp: new Date(),
            type: chatConfig.messageTypes.MODEL_OUTPUT_THINKING,
          } as any;

          taskMsgs.push(taskMsg);

          if (currentUserMsgId && conversationGroups.has(currentUserMsgId)) {
            const tasks = conversationGroups.get(currentUserMsgId) || [];
            tasks.push(taskMsg);
            conversationGroups.set(currentUserMsgId, tasks);
          }
        }

        // Process step.code (if it exists and includeCode is true)
        if (includeCode && step.code && step.code.content) {
          const taskMsg: TaskMessageType = {
            id: `code-${step.id}`,
            role: MESSAGE_ROLES.ASSISTANT,
            content: step.code.content,
            timestamp: new Date(),
            type: chatConfig.messageTypes.MODEL_OUTPUT_CODE,
          } as any;

          taskMsgs.push(taskMsg);

          if (currentUserMsgId && conversationGroups.has(currentUserMsgId)) {
            const tasks = conversationGroups.get(currentUserMsgId) || [];
            tasks.push(taskMsg);
            conversationGroups.set(currentUserMsgId, tasks);
          }
        }

        // Process step.output (if it exists)
        if (step.output && step.output.content) {
          const taskMsg: TaskMessageType = {
            id: `output-${step.id}`,
            role: MESSAGE_ROLES.ASSISTANT,
            content: step.output.content,
            timestamp: new Date(),
            type: chatConfig.messageTypes.TOOL,
          } as any;

          taskMsgs.push(taskMsg);

          if (currentUserMsgId && conversationGroups.has(currentUserMsgId)) {
            const tasks = conversationGroups.get(currentUserMsgId) || [];
            tasks.push(taskMsg);
            conversationGroups.set(currentUserMsgId, tasks);
          }
        }
      });
    }

    // Process thinking status (if it exists at message level)
    if (message.thinking && message.thinking.length > 0) {
      message.thinking.forEach((thinking, index) => {
        const taskMsg: TaskMessageType = {
          id: `thinking-${message.id}-${index}`,
          role: MESSAGE_ROLES.ASSISTANT,
          content: thinking.content,
          timestamp: new Date(),
          type: chatConfig.messageTypes.MODEL_OUTPUT_THINKING,
        } as any;

        taskMsgs.push(taskMsg);

        if (currentUserMsgId && conversationGroups.has(currentUserMsgId)) {
          const tasks = conversationGroups.get(currentUserMsgId) || [];
          tasks.push(taskMsg);
          conversationGroups.set(currentUserMsgId, tasks);
        }
      });
    }
  });

  // Process complete messages and release buffered truncation messages
  messages.forEach((message) => {
    if (message.role === MESSAGE_ROLES.ASSISTANT && message.steps) {
      message.steps.forEach((step) => {
        if (step.contents && step.contents.length > 0) {
          step.contents.forEach((content: any) => {
            if (content.type === "complete") {
              // Find the related user message ID for this complete message
              let relatedUserMsgId: string | null = null;
              const messageIndex = messages.indexOf(message);
              for (let i = messageIndex - 1; i >= 0; i--) {
                if (messages[i].role === "user" && messages[i].id) {
                  relatedUserMsgId = messages[i].id;
                  break;
                }
              }

              if (relatedUserMsgId && truncationBuffer.has(relatedUserMsgId)) {
                // Release buffered truncation messages
                const buffer = truncationBuffer.get(relatedUserMsgId) || [];
                buffer.forEach((truncationMsg) => {
                  taskMsgs.push(truncationMsg);
                  if (conversationGroups.has(relatedUserMsgId!)) {
                    const tasks = conversationGroups.get(relatedUserMsgId!) || [];
                    tasks.push(truncationMsg);
                    conversationGroups.set(relatedUserMsgId!, tasks);
                  }
                });
                truncationBuffer.delete(relatedUserMsgId);
              }
            }
          });
        }
      });
    }
  });

  // Check and delete empty task groups
  for (const [key, value] of conversationGroups.entries()) {
    if (value.length === 0) {
      conversationGroups.delete(key);
    }
  }

  return {
    taskMessages: taskMsgs,
    conversationGroups,
  };
}

