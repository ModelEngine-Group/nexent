"use client"

import { useState, useRef } from 'react'
import { Typography, Input, Button } from 'antd'
import { useTranslation } from 'react-i18next'
import { conversationService } from '@/services/conversationService'
import { handleStreamResponse } from '@/app/chat/streaming/chatStreamHandler'
import { ChatMessageType, TaskMessageType } from '@/types/chat'
import { ChatStreamFinalMessage } from '@/app/chat/streaming/chatStreamFinalMessage'
import { TaskWindow } from '@/app/chat/streaming/taskWindow'

const { Text } = Typography

// Agent debugging component Props interface
interface AgentDebuggingProps {
  question: string;
  answer: string;
  onAskQuestion: (question: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  messages: ChatMessageType[];
  taskMessages: TaskMessageType[];
  conversationGroups: Map<string, TaskMessageType[]>;
}

// Main component Props interface
interface DebugConfigProps {
  testQuestion: string;
  setTestQuestion: (question: string) => void;
  testAnswer: string;
  setTestAnswer: (answer: string) => void;
  agentId?: number; // Make agentId an optional prop
}

// Counter for generating unique IDs
const stepIdCounter = { current: 0 };

/**
 * Agent debugging component
 */
function AgentDebugging({ 
  question, 
  answer, 
  onAskQuestion,
  onStop,
  isStreaming,
  messages,
  taskMessages,
  conversationGroups
}: AgentDebuggingProps) {
  const { t } = useTranslation()
  const [inputQuestion, setInputQuestion] = useState("")
  
  const handleSend = async () => {
    if (!inputQuestion.trim()) return;
    
    try {
      await onAskQuestion(inputQuestion);
      setInputQuestion("");
    } catch (error) {
      console.error(t('agent.error.loadTools'), error);
    }
  }
  
  // Process the step content of the message
  const processMessageSteps = (message: ChatMessageType): TaskMessageType[] => {
    if (!message.steps || message.steps.length === 0) return [];
    
    const taskMsgs: TaskMessageType[] = [];
    message.steps.forEach(step => {
      // Process step.contents
      if (step.contents && step.contents.length > 0) {
        step.contents.forEach(content => {
          taskMsgs.push({
            id: content.id,
            role: "assistant",
            content: content.content,
            timestamp: new Date(),
            type: content.type,
            // Preserve subType so TaskWindow can style deep thinking text
            subType: content.subType as any
          } as any);
        });
      }
      
      // Process step.thinking
      if (step.thinking && step.thinking.content) {
        taskMsgs.push({
          id: `thinking-${step.id}`,
          role: "assistant",
          content: step.thinking.content,
          timestamp: new Date(),
          type: "model_output_thinking"
        });
      }
      
      // Process step.code 
      if (step.code && step.code.content) {
        taskMsgs.push({
          id: `code-${step.id}`,
          role: "assistant",
          content: step.code.content,
          timestamp: new Date(),
          type: "model_output_code"
        });
      }
      
      // Process step.output
      if (step.output && step.output.content) {
        taskMsgs.push({
          id: `output-${step.id}`,
          role: "assistant",
          content: step.output.content,
          timestamp: new Date(),
          type: "tool"
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
            const currentTaskMessages = message.role === "assistant" ? processMessageSteps(message) : [];
            
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
                {message.role === "assistant" && currentTaskMessages.length > 0 && (
                  <TaskWindow
                    messages={currentTaskMessages}
                    isStreaming={isStreaming && index === messages.length - 1}
                  />
                )}
                
                {/* Assistant message final answer */}
                {message.role === "assistant" && (
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
          placeholder={t('agent.debug.placeholder')}
          onPressEnter={handleSend}
          disabled={isStreaming}
        />
        {isStreaming ? (
          <button
            onClick={onStop}
            className="min-w-[56px] px-4 py-1.5 rounded-md flex items-center justify-center text-sm bg-red-500 hover:bg-red-600 text-white whitespace-nowrap"
            style={{ border: "none" }}
          >
            {t('agent.debug.stop')}
          </button>
        ) : (
          <button
            onClick={handleSend}
            className="min-w-[56px] px-4 py-1.5 rounded-md flex items-center justify-center text-sm bg-blue-500 hover:bg-blue-600 text-white whitespace-nowrap"
            style={{ border: "none" }}
          >
            {t('agent.debug.send')}
          </button>
        )}
      </div>
    </div>
  )
}

/**
 * Debug configuration main component
 */
export default function DebugConfig({
  testQuestion,
  setTestQuestion,
  testAnswer,
  setTestAnswer,
  agentId
}: DebugConfigProps) {
  const { t } = useTranslation()
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [taskMessages, setTaskMessages] = useState<TaskMessageType[]>([]);
  const [conversationGroups] = useState<Map<string, TaskMessageType[]>>(new Map());
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

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
        abortControllerRef.current.abort(t('agent.debug.userStop'));
      } catch (error) {
        console.error(t('agent.debug.cancelError'), error);
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
      console.error(t('agent.debug.stopError'), error);
      // This is expected if no agent is running for debug mode
    }

    // Manually update messages, clear thinking state
    setMessages(prev => {
      const newMessages = [...prev];
      const lastMsg = newMessages[newMessages.length - 1];
      if (lastMsg && lastMsg.role === "assistant") {
        lastMsg.isComplete = true;
        lastMsg.thinking = undefined; // Explicitly clear thinking state
        lastMsg.content = t('agent.debug.stopped');
      }
      return newMessages;
    });
  };

  // Process test question
  const handleTestQuestion = async (question: string) => {
    setTestQuestion(question);
    setIsStreaming(true);
    
    // Create new AbortController for this request
    abortControllerRef.current = new AbortController();
    
    // Add user message
    const userMessage: ChatMessageType = {
      id: Date.now().toString(),
      role: "user",
      content: question,
      timestamp: new Date()
    };
    
    // Add assistant message (initial state)
    const assistantMessage: ChatMessageType = {
      id: (Date.now() + 1).toString(),
      role: "assistant",
      content: "",
      timestamp: new Date(),
      isComplete: false
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
      const reader = await conversationService.runAgent({
        query: question,
        conversation_id: -1, // Debug mode uses -1 as conversation ID
        is_set: true,
        history: [],
        is_debug: true,  // Add debug mode flag
        agent_id: agentIdValue  // Use the properly parsed agent_id
      }, abortControllerRef.current.signal); // Pass AbortSignal

      if (!reader) throw new Error(t('agent.debug.nullResponse'));

      // Process stream response
      await handleStreamResponse(
        reader,
        setMessages,
        resetTimeout,
        stepIdCounter,
        () => {}, // setIsSwitchedConversation - Debug mode does not need
        false, // isNewConversation - Debug mode does not need
        () => {}, // setConversationTitle - Debug mode does not need
        async () => {}, // fetchConversationList - Debug mode does not need
        -1, // currentConversationId - Debug mode uses -1
        conversationService,
        true, // isDebug: true for debug mode
        t
      );

      // Update final answer
      const lastMessage = messages[messages.length - 1];
      if (lastMessage && lastMessage.role === "assistant") {
        setTestAnswer(lastMessage.finalAnswer || lastMessage.content || "");
      }
    } catch (error) {
      // If user actively canceled, don't show error message
      const err = error as Error;
      if (err.name === 'AbortError') {
        setMessages(prev => {
          const newMessages = [...prev];
          const lastMsg = newMessages[newMessages.length - 1];
          if (lastMsg && lastMsg.role === "assistant") {
            lastMsg.content = t('agent.debug.stopped');
            lastMsg.isComplete = true;
            lastMsg.thinking = undefined; // Explicitly clear thinking state
          }
          return newMessages;
        });
      } else {
        console.error(t('agent.debug.streamError'), error);
        const errorMessage = error instanceof Error ? error.message : t('agent.debug.processError');
        
        setMessages(prev => {
          const newMessages = [...prev];
          const lastMsg = newMessages[newMessages.length - 1];
          if (lastMsg && lastMsg.role === "assistant") {
            lastMsg.content = errorMessage;
            lastMsg.isComplete = true;
            lastMsg.error = errorMessage;
          }
          return newMessages;
        });
        
        setTestAnswer(errorMessage);
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
        question={testQuestion} 
        answer={testAnswer} 
        onAskQuestion={handleTestQuestion}
        onStop={handleStop}
        isStreaming={isStreaming}
        messages={messages}
        taskMessages={taskMessages}
        conversationGroups={conversationGroups}
      />
    </div>
  )
} 