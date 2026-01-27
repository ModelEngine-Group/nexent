import { useMemo } from 'react';

import { MESSAGE_ROLES } from '@/const/chatConfig';
import { ChatMessageType, TaskMessageType, MessageGroup, ChatTaskMessageResult } from '@/types/chat';

export function useChatTaskMessage(messages: ChatMessageType[]): ChatTaskMessageResult {
  // Filter visible messages
  const visibleMessages = useMemo(() => 
    messages.filter(message => 
      (message as TaskMessageType).type !== "final_answer" && 
      (message as TaskMessageType).type !== "execution"
    ) as TaskMessageType[],
    [messages]
  );

  // Group messages
  const groupedMessages = useMemo(() => {
    const groups: MessageGroup[] = [];
    let cardMessages: TaskMessageType[] = [];
    
    visibleMessages.forEach(message => {
      if (message.type === "card") {
        // Collect card messages
        cardMessages.push(message);
      } else {
        // If there is a non-card message before, push it together with the card
        if (groups.length > 0) {
          const lastGroup = groups[groups.length - 1];
          lastGroup.cards = [...cardMessages];
          cardMessages = []; // Reset card collector
        }
        
        // Add new non-card message
        groups.push({
          message,
          cards: []
        });
      }
    });
    
    // Handle remaining cards after the loop
    if (cardMessages.length > 0) {
      if (groups.length > 0) {
        // If there are other messages, append the card to the last message
        const lastGroup = groups[groups.length - 1];
        lastGroup.cards = [...cardMessages];
      } else {
        // If there is only card message, create a virtual message group
        groups.push({
          message: {
            id: `virtual-${Date.now()}`,
            role: MESSAGE_ROLES.ASSISTANT,
            type: "virtual",
            content: "",
            timestamp: new Date()
          } as TaskMessageType,
          cards: cardMessages
        });
      }
    }

    return groups;
  }, [visibleMessages]);

  return {
    visibleMessages,
    groupedMessages,
    hasMessages: messages.length > 0,
    hasVisibleMessages: visibleMessages.length > 0
  };
} 