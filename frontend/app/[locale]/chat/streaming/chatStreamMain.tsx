import { useRef, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

import { ScrollArea } from "@/components/ui/scrollArea";
import { Button } from "@/components/ui/button";
import { ROLE_ASSISTANT } from "@/const/agentConfig";
import { chatConfig } from "@/const/chatConfig";
import { USER_ROLES } from "@/const/modelConfig";
import { ChatMessageType, ProcessedMessages, ChatStreamMainProps } from "@/types/chat";

import { ChatInput } from "../components/chatInput";
import { ChatStreamFinalMessage } from "./chatStreamFinalMessage";
import { TaskWindow } from "./taskWindow";

export function ChatStreamMain({
  messages,
  input,
  isLoading,
  isStreaming = false,
  isLoadingHistoricalConversation = false,
  conversationLoadError,
  onInputChange,
  onSend,
  onStop,
  onKeyDown,
  onSelectMessage,
  selectedMessageId,
  onImageClick,
  attachments,
  onAttachmentsChange,
  onFileUpload,
  onImageUpload,
  onOpinionChange,
  currentConversationId,
  shouldScrollToBottom,
  selectedAgentId,
  onAgentSelect,
  onCitationHover,
  onScroll,
}: ChatStreamMainProps) {
  const { t } = useTranslation();
  // Animation variants for ChatInput
  const chatInputVariants = {
    initial: {
      opacity: 0,
      y: 80,
    },
    animate: {
      opacity: 1,
      y: 0,
    },
  };

  const chatInputTransition = {
    type: "spring" as const,
    stiffness: 300,
    damping: 80,
  };
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const chatInputRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const [showTopFade, setShowTopFade] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [chatInputHeight, setChatInputHeight] = useState(130); // Default ChatInput height
  const [processedMessages, setProcessedMessages] = useState<ProcessedMessages>(
    {
      finalMessages: [],
      taskMessages: [],
      conversationGroups: new Map(),
    }
  );
  const lastUserMessageIdRef = useRef<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Monitor ChatInput height changes
  useEffect(() => {
    const chatInputElement = chatInputRef.current;
    if (!chatInputElement) return;

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const height = entry.contentRect.height;
        setChatInputHeight(height);
      }
    });

    resizeObserver.observe(chatInputElement);

    // Set initial height
    setChatInputHeight(chatInputElement.getBoundingClientRect().height);

    return () => {
      resizeObserver.disconnect();
    };
  }, [processedMessages.finalMessages.length]); // Re-observe when messages change (initial vs regular mode)

  // Handle message classification
  useEffect(() => {
    const finalMsgs: ChatMessageType[] = [];
      const taskMsgs: any[] = [];
      const conversationGroups = new Map<string, any[]>();
      const truncationBuffer = new Map<string, any[]>(); // Buffer for truncation messages by user message ID
      const processedTruncationIds = new Set<string>(); // Track processed truncation messages to avoid duplicates

      // First preprocess, find all user message IDs and initialize task groups
      messages.forEach((message) => {
        if (message.role === USER_ROLES.USER && message.id) {
          conversationGroups.set(message.id, []);
          truncationBuffer.set(message.id, []); // Initialize truncation buffer for each user message
        }
      });

    let currentUserMsgId: string | null = null;

    // Process all messages, distinguish user messages, final answers, and task messages
    messages.forEach((message) => {
      // User messages are directly added to the final message array
      if (message.role === USER_ROLES.USER) {
        finalMsgs.push(message);
        // Record the user message ID, used to associate subsequent tasks
        if (message.id) {
          currentUserMsgId = message.id;

          // Save the latest user message ID to the ref
          lastUserMessageIdRef.current = message.id;
        }
      }
      // Assistant messages need further processing
      else if (message.role === ROLE_ASSISTANT) {
        // If there is a final answer or content (including empty string), add it to the final message array
        if (message.finalAnswer || message.content !== undefined) {
          finalMsgs.push(message);
          // Do not reset currentUserMsgId here, continue to use it to associate tasks
        }

        // Process all steps and content as task messages
        if (message.steps && message.steps.length > 0) {
          message.steps.forEach((step) => {
            // Process step.contents (if it exists)
            if (step.contents && step.contents.length > 0) {
              step.contents.forEach((content: any) => {
                const taskMsg = {
                  type: content.type,
                  subType: content.subType, // Preserve subType for styling (e.g., deep_thinking)
                  content: content.content,
                  id: content.id,
                  assistantId: message.id,
                  relatedUserMsgId: currentUserMsgId,
                  // For preprocess messages, include the full contents array for TaskWindow
                  contents: content.type === chatConfig.contentTypes.PREPROCESS ? step.contents : undefined,
                };

                // Handle truncation messages specially - buffer them instead of adding immediately
                if (content.type === "truncation") {
                  // Create a unique ID for this truncation message to avoid duplicates
                  const truncationId = `${content.filename || 'unknown'}_${content.message || ''}_${currentUserMsgId || 'no_user'}`;

                  // Only add if not already processed
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
                  if (
                    currentUserMsgId &&
                    conversationGroups.has(currentUserMsgId)
                  ) {
                    const tasks = conversationGroups.get(currentUserMsgId) || [];
                    tasks.push(taskMsg);
                    conversationGroups.set(currentUserMsgId, tasks);
                  }
                }
              });
            }

            // Process step.thinking (if it exists)
            if (step.thinking && step.thinking.content) {
              const taskMsg = {
                type: chatConfig.messageTypes.MODEL_OUTPUT_THINKING,
                content: step.thinking.content,
                id: `thinking-${step.id}`,
                assistantId: message.id,
                relatedUserMsgId: currentUserMsgId,
              };
              taskMsgs.push(taskMsg);

              // If there is a related user message, add it to the corresponding task group
              if (
                currentUserMsgId &&
                conversationGroups.has(currentUserMsgId)
              ) {
                const tasks = conversationGroups.get(currentUserMsgId) || [];
                tasks.push(taskMsg);
                conversationGroups.set(currentUserMsgId, tasks);
              }
            }

            // Process step.code (if it exists)
            if (step.code && step.code.content) {
              const taskMsg = {
                type: chatConfig.messageTypes.MODEL_OUTPUT_CODE,
                content: step.code.content,
                id: `code-${step.id}`,
                assistantId: message.id,
                relatedUserMsgId: currentUserMsgId,
              };
              taskMsgs.push(taskMsg);

              // If there is a related user message, add it to the corresponding task group
              if (
                currentUserMsgId &&
                conversationGroups.has(currentUserMsgId)
              ) {
                const tasks = conversationGroups.get(currentUserMsgId) || [];
                tasks.push(taskMsg);
                conversationGroups.set(currentUserMsgId, tasks);
              }
            }

            // Process step.output (if it exists)
            if (step.output && step.output.content) {
              const taskMsg = {
                type: chatConfig.messageTypes.TOOL,
                content: step.output.content,
                id: `output-${step.id}`,
                assistantId: message.id,
                relatedUserMsgId: currentUserMsgId,
              };
              taskMsgs.push(taskMsg);

              // If there is a related user message, add it to the corresponding task group
              if (
                currentUserMsgId &&
                conversationGroups.has(currentUserMsgId)
              ) {
                const tasks = conversationGroups.get(currentUserMsgId) || [];
                tasks.push(taskMsg);
                conversationGroups.set(currentUserMsgId, tasks);
              }
            }
          });
        }

        // Process thinking status (if it exists)
        if (message.thinking && message.thinking.length > 0) {
          message.thinking.forEach((thinking, index) => {
            const taskMsg = {
              type: chatConfig.messageTypes.MODEL_OUTPUT_THINKING,
              content: thinking.content,
              id: `thinking-${message.id}-${index}`,
              assistantId: message.id,
              relatedUserMsgId: currentUserMsgId,
            };
            taskMsgs.push(taskMsg);

            // If there is a related user message, add it to the corresponding task group
            if (currentUserMsgId && conversationGroups.has(currentUserMsgId)) {
              const tasks = conversationGroups.get(currentUserMsgId) || [];
              tasks.push(taskMsg);
              conversationGroups.set(currentUserMsgId, tasks);
            }
          });
        }
      }
    });

    // Process complete messages and release buffered truncation messages
    messages.forEach((message) => {
      if (message.role === ROLE_ASSISTANT && message.steps) {
        message.steps.forEach((step) => {
          if (step.contents && step.contents.length > 0) {
            step.contents.forEach((content: any) => {
              if (content.type === "complete") {
                // Find the related user message ID for this complete message
                let relatedUserMsgId: string | null = null;

                // Find the user message that this assistant message is responding to
                const messageIndex = messages.indexOf(message);
                for (let i = messageIndex - 1; i >= 0; i--) {
                  if (messages[i].role === "user" && messages[i].id) {
                    relatedUserMsgId = messages[i].id;
                    break;
                  }
                }

                if (relatedUserMsgId && truncationBuffer.has(relatedUserMsgId)) {
                  // Clear the buffer for this user message
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

    setProcessedMessages({
      finalMessages: finalMsgs,
      taskMessages: taskMsgs,
      conversationGroups: conversationGroups,
    });
  }, [messages]);

  // Listen for scroll events
  useEffect(() => {
    const scrollAreaElement = scrollAreaRef.current?.querySelector(
      "[data-radix-scroll-area-viewport]"
    );

    if (!scrollAreaElement) return;

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } =
        scrollAreaElement as HTMLElement;
      const distanceToBottom = scrollHeight - scrollTop - clientHeight;

      // Show/hide the scroll to bottom button
      if (distanceToBottom > 100) {
        setShowScrollButton(true);
      } else {
        setShowScrollButton(false);
      }

      // Show top gradient effect
      if (scrollTop > 10) {
        setShowTopFade(true);
      } else {
        setShowTopFade(false);
      }

      // Only if shouldScrollToBottom is false does autoScroll adjust based on user scroll position.
      if (!shouldScrollToBottom) {
        if (distanceToBottom < 50) {
          setAutoScroll(true);
        } else if (distanceToBottom > 80) {
          setAutoScroll(false);
        }
      }

      // Clear completed conversation indicator when scrolling
      if (onScroll) {
        onScroll();
      }
    };

    // Add scroll event listener
    scrollAreaElement.addEventListener("scroll", handleScroll);

    // Execute a check once on initialization
    handleScroll();

    return () => {
      scrollAreaElement.removeEventListener("scroll", handleScroll);
    };
  }, [shouldScrollToBottom, onScroll]);

  // Scroll to bottom function
  const scrollToBottom = (smooth = false) => {
    const scrollAreaElement = scrollAreaRef.current?.querySelector(
      "[data-radix-scroll-area-viewport]"
    );
    if (!scrollAreaElement) return;

    // Use setTimeout to ensure scrolling after DOM updates
    setTimeout(() => {
      if (scrollAreaElement) {
        if (smooth) {
          scrollAreaElement.scrollTo({
            top: (scrollAreaElement as HTMLElement).scrollHeight,
            behavior: "smooth",
          });
        } else {
          (scrollAreaElement as HTMLElement).scrollTop = (
            scrollAreaElement as HTMLElement
          ).scrollHeight;
        }
      }
    }, 0);
  };

  // Force scroll to bottom when entering history conversation
  useEffect(() => {
    if (shouldScrollToBottom && processedMessages.finalMessages.length > 0) {
      setAutoScroll(true);
      scrollToBottom(false);

      setTimeout(() => {
        scrollToBottom(false);
      }, 300);
    }
  }, [shouldScrollToBottom, processedMessages.finalMessages.length]);

  // Scroll to bottom when messages are updated (if user is already at the bottom)
  useEffect(() => {
    if (processedMessages.finalMessages.length > 0 && autoScroll) {
      const scrollAreaElement = scrollAreaRef.current?.querySelector(
        "[data-radix-scroll-area-viewport]"
      );
      if (!scrollAreaElement) return;

      const { scrollTop, scrollHeight, clientHeight } =
        scrollAreaElement as HTMLElement;
      const distanceToBottom = scrollHeight - scrollTop - clientHeight;

      // When shouldScrollToBottom is true, force scroll to the bottom, regardless of distance.
      if (shouldScrollToBottom || distanceToBottom < 50) {
        scrollToBottom();
      }
    }
  }, [
    processedMessages.finalMessages.length,
    processedMessages.conversationGroups.size,
    autoScroll,
    shouldScrollToBottom,
  ]);

  // Additional scroll trigger for async content like Mermaid diagrams
  useEffect(() => {
    if (processedMessages.finalMessages.length > 0 && autoScroll) {
      const scrollAreaElement = scrollAreaRef.current?.querySelector(
        "[data-radix-scroll-area-viewport]"
      );
      if (!scrollAreaElement) return;

      // Use ResizeObserver to detect when content height changes (e.g., Mermaid diagrams finish rendering)
      const resizeObserver = new ResizeObserver(() => {
        const { scrollTop, scrollHeight, clientHeight } =
          scrollAreaElement as HTMLElement;
        const distanceToBottom = scrollHeight - scrollTop - clientHeight;

        // Auto-scroll if user is near bottom and content height changed
        if (distanceToBottom < 100) {
          scrollToBottom();
        }
      });

      resizeObserver.observe(scrollAreaElement);

      // Also use a timeout as fallback for async content
      const timeoutId = setTimeout(() => {
        const { scrollTop, scrollHeight, clientHeight } =
          scrollAreaElement as HTMLElement;
        const distanceToBottom = scrollHeight - scrollTop - clientHeight;

        if (distanceToBottom < 100) {
          scrollToBottom();
        }
      }, 1000); // Wait 1 second for async content to render

      return () => {
        resizeObserver.disconnect();
        clearTimeout(timeoutId);
      };
    }
  }, [processedMessages.finalMessages.length, autoScroll]);

  // Scroll to bottom when task messages are updated
  useEffect(() => {
    if (autoScroll) {
      const scrollAreaElement = scrollAreaRef.current?.querySelector(
        "[data-radix-scroll-area-viewport]"
      );
      if (!scrollAreaElement) return;

      const { scrollTop, scrollHeight, clientHeight } =
        scrollAreaElement as HTMLElement;
      const distanceToBottom = scrollHeight - scrollTop - clientHeight;

      // When shouldScrollToBottom is true, force scroll to the bottom, regardless of distance.
      if (shouldScrollToBottom || distanceToBottom < 150) {
        scrollToBottom();
      }
    }
  }, [
    processedMessages.taskMessages.length,
    isStreaming,
    autoScroll,
    shouldScrollToBottom,
  ]);

  return (
    <div className="flex-1 flex flex-col overflow-hidden relative custom-scrollbar">
      {/* Main message area */}
      <ScrollArea className="flex-1 px-4 pt-4" ref={scrollAreaRef}>
        <div className="max-w-3xl mx-auto">
          {processedMessages.finalMessages.length === 0 ? (
            isLoadingHistoricalConversation ? (
              // when loading historical conversation, show empty area
              <div className="flex flex-col items-center justify-center min-h-[calc(100vh-200px)]">
                <div className="text-gray-500 text-sm">
                  {t("chatStreamMain.loadingConversation")}
                </div>
              </div>
            ) : conversationLoadError ? (
              // when conversation load error, show error message
              <div className="flex flex-col items-center justify-center min-h-[calc(100vh-200px)]">
                <div className="text-center max-w-md">
                  <div className="text-red-500 text-sm mb-4">
                    {t("chatStreamMain.loadError")}
                  </div>
                  <div className="text-gray-500 text-xs mb-4">
                    {conversationLoadError}
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      // Trigger a page refresh to retry loading
                      window.location.reload();
                    }}
                  >
                    {t("chatStreamMain.retry")}
                  </Button>
                </div>
              </div>
            ) : (
              // when new conversation, show input interface
              <div className="flex flex-col items-center justify-center min-h-[calc(100vh-200px)]">
                <div className="w-full max-w-3xl">
                  <AnimatePresence mode="wait">
                    <motion.div
                      key="initial-chat-input"
                      initial="initial"
                      animate="animate"
                      variants={chatInputVariants}
                      transition={chatInputTransition}
                      ref={chatInputRef}
                    >
                      <ChatInput
                        input={input}
                        isLoading={isLoading}
                        isStreaming={isStreaming}
                        isInitialMode={true}
                        onInputChange={onInputChange}
                        onSend={onSend}
                        onStop={onStop}
                        onKeyDown={onKeyDown}
                        attachments={attachments}
                        onAttachmentsChange={onAttachmentsChange}
                        onFileUpload={onFileUpload}
                        onImageUpload={onImageUpload}
                        selectedAgentId={selectedAgentId}
                        onAgentSelect={onAgentSelect}
                      />
                    </motion.div>
                  </AnimatePresence>
                </div>
              </div>
            )
          ) : (
            <>
              {processedMessages.finalMessages.map((message, index) => (
                <div key={message.id || index} className="flex flex-col gap-2">
                  <ChatStreamFinalMessage
                    message={message}
                    onSelectMessage={onSelectMessage}
                    isSelected={message.id === selectedMessageId}
                    searchResultsCount={message?.searchResults?.length || 0}
                    imagesCount={message?.images?.length || 0}
                    onImageClick={onImageClick}
                    onOpinionChange={onOpinionChange}
                    index={index}
                    currentConversationId={currentConversationId}
                    onCitationHover={onCitationHover}
                  />
                  {message.role === "user" &&
                    processedMessages.conversationGroups.has(message.id!) && (
                      <div className="transition-all duration-500 opacity-0 translate-y-4 animate-task-window">
                        <TaskWindow
                          messages={
                            processedMessages.conversationGroups.get(
                              message.id!
                            ) || []
                          }
                          isStreaming={
                            isStreaming &&
                            lastUserMessageIdRef.current === message.id
                          }
                        />
                      </div>
                    )}
                </div>
              ))}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>
      </ScrollArea>

      {/* Top fade effect */}
      {showTopFade && (
        <div className="absolute top-0 left-0 right-0 h-16 pointer-events-none z-10 bg-gradient-to-b from-background to-transparent"></div>
      )}

      {/* Scroll to bottom button - dynamically positioned based on ChatInput height */}
      {showScrollButton && (
        <Button
          variant="outline"
          size="icon"
          className="absolute left-1/2 transform -translate-x-1/2 z-20 rounded-full shadow-md bg-background hover:bg-background/90 border border-border h-8 w-8"
          style={{
            // Position the button above the ChatInput with some margin
            // The ChatInput height changes from 130px (default) to up to 200px+ when textarea expands
            bottom: `${chatInputHeight-15}px`
          }}
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            scrollToBottom(true);
          }}
        >
          <ChevronDown className="h-4 w-4" />
        </Button>
      )}

      {/* Input box in non-initial mode */}
      {processedMessages.finalMessages.length > 0 && (
        <AnimatePresence mode="wait">
          <motion.div
            key="regular-chat-input"
            initial="initial"
            animate="animate"
            variants={chatInputVariants}
            transition={chatInputTransition}
            ref={chatInputRef}
          >
            <ChatInput
              input={input}
              isLoading={isLoading}
              isStreaming={isStreaming}
              onInputChange={onInputChange}
              onSend={onSend}
              onStop={onStop}
              onKeyDown={onKeyDown}
              attachments={attachments}
              onAttachmentsChange={onAttachmentsChange}
              onFileUpload={onFileUpload}
              onImageUpload={onImageUpload}
              selectedAgentId={selectedAgentId}
              onAgentSelect={onAgentSelect}
            />
          </motion.div>
        </AnimatePresence>
      )}

      {/* Add animation keyframes */}
      <style jsx global>{`
        @keyframes taskWindowEnter {
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
        .animate-task-window {
          animation: taskWindowEnter 0.5s ease-out forwards;
        }
      `}</style>
    </div>
  );
}
