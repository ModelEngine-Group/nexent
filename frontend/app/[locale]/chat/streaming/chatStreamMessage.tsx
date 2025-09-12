import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Copy,
  Volume2,
  ChevronRight,
  SquareCheckBig,
  Loader2,
} from "lucide-react";
import { FaRegThumbsDown, FaRegThumbsUp } from "react-icons/fa";

import { MarkdownRenderer } from "@/components/ui/markdownRenderer";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ROLE_ASSISTANT } from "@/const/agentConfig";
import { chatConfig, Opinion } from "@/const/chatConfig";
import { USER_ROLES } from "@/const/modelConfig";
import { AttachmentItem, ChatMessageType } from "@/types/chat";
import { useConfig } from "@/hooks/useConfig";
import { copyToClipboard } from "@/lib/clipboard";
import log from "@/lib/logger";

import { ChatAttachment } from "../internal/chatAttachment";

interface StreamMessageProps {
  message: ChatMessageType;
  onSelectMessage?: (messageId: string) => void;
  isSelected?: boolean;
  searchResultsCount?: number;
  imagesCount?: number;
  onImageClick?: (imageUrl: string) => void;
  onOpinionChange?: (messageId: number, opinion: Opinion) => void;
}

export function ChatStreamMessage({
  message,
  onSelectMessage,
  isSelected = false,
  searchResultsCount = 0,
  imagesCount = 0,
  onImageClick,
  onOpinionChange,
}: StreamMessageProps) {
  const { t } = useTranslation("common");
  const { getAppAvatarUrl } = useConfig();
  const avatarUrl = getAppAvatarUrl(20); // Message avatar size is 20px

  const messageRef = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);
  const [localOpinion, setLocalOpinion] = useState<string | null>(
    message.opinion_flag ?? null
  );
  const [isVisible, setIsVisible] = useState(false);

  // Animation effect - message enters with fade-in
  useEffect(() => {
    const timer = setTimeout(() => {
      setIsVisible(true);
    }, 10);
    return () => clearTimeout(timer);
  }, []);

  // When the message is updated, scroll the element into the visible area
  useEffect(() => {
    if (
      message.role === ROLE_ASSISTANT &&
      !message.isComplete &&
      messageRef.current
    ) {
      messageRef.current.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [message.content, message.isComplete, message.role]);

  // Update opinion status
  useEffect(() => {
    setLocalOpinion(message.opinion_flag ?? null);
  }, [message.opinion_flag]);

  // Copy content to clipboard
  const handleCopyContent = () => {
    const contentToCopy = message.finalAnswer || message.content;
    if (!contentToCopy) return;

    copyToClipboard(contentToCopy)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      })
      .catch((err) => {
        log.error(t("chatStreamMessage.copyFailed"), err);
      });
  };

  // Handle likes
  const handleThumbsUp = () => {
    const newOpinion = localOpinion === chatConfig.opinion.POSITIVE ? null : chatConfig.opinion.POSITIVE;
    setLocalOpinion(newOpinion);
    if (onOpinionChange && message.message_id) {
      onOpinionChange(message.message_id, newOpinion as Opinion);
    }
  };

  // Handle dislikes
  const handleThumbsDown = () => {
    const newOpinion = localOpinion === chatConfig.opinion.NEGATIVE ? null : chatConfig.opinion.NEGATIVE;
    setLocalOpinion(newOpinion);
    if (onOpinionChange && message.message_id) {
      onOpinionChange(message.message_id, newOpinion as Opinion);
    }
  };

  // Handle message selection
  const handleMessageSelect = () => {
    if (message.id && onSelectMessage) {
      onSelectMessage(message.id);
    }
  };

  return (
    <div
      ref={messageRef}
      className={`flex gap-2 mb-6 transition-all duration-500 ${
        message.role === "user" ? "flex-row-reverse" : ""
      } ${
        !isVisible ? "opacity-0 translate-y-4" : "opacity-100 translate-y-0"
      }`}
    >
      {/* Avatar section - only show avatar for AI assistant */}
      {message.role === ROLE_ASSISTANT && (
        <div className="flex-shrink-0">
          <div className="h-8 w-8 rounded-full overflow-hidden bg-primary/10">
            <img
              src={avatarUrl}
              alt={t("chatStreamMessage.appIconAlt")}
              className="h-full w-full object-cover"
            />
          </div>
        </div>
      )}

      {/* Message content section */}
      <div
        className={`${
          message.role === USER_ROLES.USER
            ? "flex items-end flex-col w-full"
            : "flex-1 max-w-[calc(100%-60px)]"
        }`}
      >
        {/* User message section */}
        {message.role === USER_ROLES.USER && (
          <>
            {/* Attachment section - placed above text */}
            {message.attachments && message.attachments.length > 0 && (
              <div className="mb-2 w-full flex justify-end">
                <div className="max-w-[80%]">
                  <ChatAttachment
                    attachments={message.attachments as AttachmentItem[]}
                    onImageClick={onImageClick}
                    className="justify-end" // Right align
                  />
                </div>
              </div>
            )}

            {/* Text content */}
            {message.content && (
              <div className="rounded-lg border bg-blue-50 border-blue-100 user-message-container py-2 px-3 ml-auto text-normal">
                <div className="user-message-content whitespace-pre-wrap">
                  {message.content}
                </div>
              </div>
            )}
          </>
        )}

        {/* Assistant message section */}
        {message.role === ROLE_ASSISTANT && (
          <>
            {/* Attachment section - placed above text */}
            {message.attachments && message.attachments.length > 0 && (
              <div className="mb-2 w-full">
                <div className="max-w-[80%]">
                  <ChatAttachment
                    attachments={message.attachments as AttachmentItem[]}
                    onImageClick={onImageClick}
                  />
                </div>
              </div>
            )}

            {/* Text content - streaming rendering area */}
            {message.content && (
              <div
                className={`rounded-lg border mr-auto bg-white border-gray-200 w-full p-3 text-sm ${
                  !message.isComplete
                    ? "border-l-4 border-l-blue-400 shadow-sm shadow-blue-100"
                    : ""
                }`}
              >
                <MarkdownRenderer content={message.content} />
              </div>
            )}

            {/* Thinking status */}
            {!message.isComplete &&
              message.thinking &&
              message.thinking.length > 0 && (
                <div className="flex items-center mt-2 ml-2">
                  <Loader2 className="h-4 w-4 animate-spin mr-2 text-blue-500" />
                  <div className="text-sm text-gray-500">
                    {message.thinking[0].content}
                  </div>
                </div>
              )}

            {/* Final answer */}
            {message.finalAnswer && (
              <div className="mt-4 rounded-lg border border-gray-200 shadow-sm transition-all duration-500">
                <div className="flex items-center w-full py-2 px-3 font-medium bg-gradient-to-r from-purple-50 to-transparent border-b border-gray-200">
                  <SquareCheckBig className="h-4 w-4 mr-2 text-purple-500" />
                  <span className="font-medium">
                    {t("chatStreamMessage.finalAnswer")}
                  </span>
                </div>
                <div className="px-3 pb-3">
                  <MarkdownRenderer
                    content={message.finalAnswer}
                    searchResults={message?.searchResults}
                  />

                  {/* Button group */}
                  <div className="flex items-center justify-between mt-3">
                    {/* Source button */}
                    {((message?.searchResults &&
                      message.searchResults.length > 0) ||
                      (message?.images && message.images.length > 0)) && (
                      <div className="flex items-center text-xs text-gray-500">
                        <Button
                          variant="ghost"
                          size="sm"
                          className={`flex items-center gap-1 p-1 pl-3 hover:bg-gray-100 rounded transition-all duration-200 border border-gray-200 ${
                            isSelected ? "bg-gray-100" : ""
                          }`}
                          onClick={handleMessageSelect}
                        >
                          <span>
                            {searchResultsCount > 0 &&
                              t("chatStreamMessage.sources", {
                                count: searchResultsCount,
                              })}
                            {searchResultsCount > 0 && imagesCount > 0 && ", "}
                            {imagesCount > 0 &&
                              t("chatStreamMessage.images", {
                                count: imagesCount,
                              })}
                          </span>
                          <ChevronRight className="h-4 w-4" />
                        </Button>
                      </div>
                    )}

                    {/* Tool button */}
                    <div className="flex items-center space-x-2 mt-3 justify-end">
                      <TooltipProvider>
                        {/* Copy button */}
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="outline"
                              size="icon"
                              className={`h-8 w-8 rounded-full bg-white hover:bg-gray-100 transition-all duration-200 shadow-sm ${
                                copied
                                  ? "bg-green-100 text-green-600 border-green-200"
                                  : ""
                              }`}
                              onClick={handleCopyContent}
                              disabled={copied}
                            >
                              <Copy className="h-4 w-4" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>
                              {copied
                                ? t("chatStreamMessage.copied")
                                : t("chatStreamMessage.copyContent")}
                            </p>
                          </TooltipContent>
                        </Tooltip>

                        {/* Like button */}
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant={
                                localOpinion === chatConfig.opinion.POSITIVE ? "secondary" : "outline"
                              }
                              size="icon"
                              className={`h-8 w-8 rounded-full ${
                                localOpinion === chatConfig.opinion.POSITIVE
                                  ? "bg-green-100 text-green-600 border-green-200"
                                  : "bg-white hover:bg-gray-100"
                              } transition-all duration-200 shadow-sm`}
                              onClick={handleThumbsUp}
                            >
                              <FaRegThumbsUp className="h-4 w-4" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>
                              {localOpinion === chatConfig.opinion.POSITIVE
                                ? t("chatStreamMessage.cancelLike")
                                : t("chatStreamMessage.like")}
                            </p>
                          </TooltipContent>
                        </Tooltip>

                        {/* Dislike button */}
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant={
                                localOpinion === chatConfig.opinion.NEGATIVE ? "secondary" : "outline"
                              }
                              size="icon"
                              className={`h-8 w-8 rounded-full ${
                                localOpinion === chatConfig.opinion.NEGATIVE
                                  ? "bg-red-100 text-red-600 border-red-200"
                                  : "bg-white hover:bg-gray-100"
                              } transition-all duration-200 shadow-sm`}
                              onClick={handleThumbsDown}
                            >
                              <FaRegThumbsDown className="h-4 w-4" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>
                              {localOpinion === chatConfig.opinion.NEGATIVE
                                ? t("chatStreamMessage.cancelDislike")
                                : t("chatStreamMessage.dislike")}
                            </p>
                          </TooltipContent>
                        </Tooltip>

                        {/* Voice announcement button */}
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="outline"
                              size="icon"
                              className="h-8 w-8 rounded-full bg-white hover:bg-gray-100 transition-all duration-200 shadow-sm"
                            >
                              <Volume2 className="h-4 w-4" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>{t("chatStreamMessage.tts")}</p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
