import { useRef, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

import { ScrollArea } from "@/components/ui/scrollArea";
import { Button } from "antd";
import { MESSAGE_ROLES } from "@/const/chatConfig";
import { ChatMessageType, ProcessedMessages, ChatStreamMainProps } from "@/types/chat";

import { ChatInput } from "../components/chatInput";
import { ChatStreamFinalMessage } from "./chatStreamFinalMessage";
import { TaskWindow } from "./taskWindow";
import { transformMessagesToTaskMessages } from "./messageTransformer";

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

    // Track the latest user message ID for scroll behavior
    messages.forEach((message) => {
      if (message.role === MESSAGE_ROLES.USER && message.id) {
        lastUserMessageIdRef.current = message.id;
      }
    });

    // Process all messages, distinguish user messages and final answers
    messages.forEach((message) => {
      // User messages are directly added to the final message array
      if (message.role === MESSAGE_ROLES.USER) {
        finalMsgs.push(message);
      }
      // Assistant messages - if there is a final answer or content, add it to the final message array
      else if (message.role === MESSAGE_ROLES.ASSISTANT) {
        if (message.finalAnswer || message.content !== undefined) {
          finalMsgs.push(message);
        }
      }
    });

    // Use unified message transformer (includeCode: false for normal chat mode)
    const { taskMessages: taskMsgs, conversationGroups } = transformMessagesToTaskMessages(
      messages,
      { includeCode: false }
    );

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
                    size="small"
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
                  {message.role === MESSAGE_ROLES.USER &&
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
          size="small"
          shape="circle"
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
