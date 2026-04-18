"use client";

import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Button, Input, Tag, Typography } from "antd";
import { Globe, Send, User, Bot, Loader2 } from "lucide-react";
import { A2AExternalAgent, a2aClientService } from "@/services/a2aService";
import log from "@/lib/logger";

const { Text } = Typography;

export interface ChatMessage {
  id: string;
  role: "user" | "agent";
  content: string;
  timestamp: Date;
}

interface A2AChatModalProps {
  open: boolean;
  onClose: () => void;
  agent: A2AExternalAgent;
}

export default function A2AChatModal({
  open,
  onClose,
  agent,
}: Readonly<A2AChatModalProps>) {
  const { t } = useTranslation("common");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  /**
   * Extract text content from A2A SendMessage response.
   * Supports multiple response formats:
   * 1. Direct message: { message: { parts: [...] } }
   * 2. Task wrapper: { task: { status: { message: { parts: [...] } } } }
   * 3. Fallback: any response with message text
   */
  const extractAgentContent = (data: any): string => {
    if (!data) return t("a2a.chat.noResponse");

    // Format 1: Direct message with parts
    if (data.message?.parts) {
      const parts = data.message.parts;
      if (Array.isArray(parts) && parts.length > 0) {
        return parts[0].text || t("a2a.chat.noResponse");
      }
    }

    // Format 1 fallback: Direct message as string
    if (typeof data.message === "string") {
      return data.message;
    }

    // Format 2: Task wrapper (A2A SendMessage standard)
    if (data.task?.status?.message?.parts) {
      const parts = data.task.status.message.parts;
      if (Array.isArray(parts) && parts.length > 0) {
        return parts[0].text || t("a2a.chat.noResponse");
      }
    }

    // Format 2 fallback: Task status message as string
    if (typeof data.task?.status?.message === "string") {
      return data.task.status.message;
    }

    // Format 3: Look for text in common locations
    if (data.text) return data.text;
    if (data.content) return typeof data.content === "string" ? data.content : data.content?.text;
    if (data.result?.text) return data.result.text;
    if (data.result?.message?.text) return data.result.message.text;

    // Last resort: stringify meaningful data
    if (data.message) return JSON.stringify(data.message);

    return t("a2a.chat.noResponse");
  };

  useEffect(() => {
    if (open) {
      setMessages([]);
      setInputValue("");
    }
  }, [open]);

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = async () => {
    if (!inputValue.trim() || sending) {
      return;
    }

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: inputValue.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue("");
    setSending(true);

    try {
      const result = await a2aClientService.sendChatMessage(
        String(agent.id),
        userMessage.content
      );

      if (result.success) {
        // Support both direct message format and Task wrapper format (A2A SendMessage standard)
        // Format 1: { message: { parts: [...] } }
        // Format 2: { task: { status: { message: { parts: [...] } } } }
        const agentContent = extractAgentContent(result.data);

        const agentMessage: ChatMessage = {
          id: `agent-${Date.now()}`,
          role: "agent",
          content: agentContent,
          timestamp: new Date(),
        };

        setMessages((prev) => [...prev, agentMessage]);
      } else {
        const errorMessage: ChatMessage = {
          id: `error-${Date.now()}`,
          role: "agent",
          content: result.message || t("a2a.chat.sendFailed"),
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, errorMessage]);
      }
    } catch (error) {
      log.error("Failed to send chat message:", error);
      const errorMessage: ChatMessage = {
        id: `error-${Date.now()}`,
        role: "agent",
        content: t("a2a.chat.sendFailed"),
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    }

    setSending(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const formatTime = (date: Date) => {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  const renderMessageContent = (content: string) => {
    return content.split("\n").map((line, index) => (
      <span key={index}>
        {line}
        {index < content.split("\n").length - 1 && <br />}
      </span>
    ));
  };

  return (
    <Modal
      title={
        <div className="flex items-center gap-2">
          <Globe size={18} className="text-blue-500" />
          <span>{t("a2a.chat.title")}</span>
          <Tag color={agent.is_available ? "success" : "error"} className="ml-2">
            {agent.is_available
              ? t("a2a.status.available")
              : t("a2a.status.unavailable")}
          </Tag>
        </div>
      }
      open={open}
      onCancel={onClose}
      footer={null}
      width={600}
      destroyOnClose
    >
      <div className="flex flex-col" style={{ height: 500 }}>
        {/* Agent Info Header */}
        <div className="flex items-center gap-2 p-3 bg-gray-50 rounded-lg mb-4">
          <Globe size={16} className="text-blue-500" />
          <Text strong>{agent.name}</Text>
          {agent.description && (
            <Text type="secondary" className="text-xs ml-2 truncate">
              {agent.description}
            </Text>
          )}
        </div>

        {/* Messages Container */}
        <div
          className="flex-1 space-y-4 p-2"
          style={{
            minHeight: 0,
            overflowY: messages.length === 0 ? "hidden" : "auto",
          }}
        >
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-gray-400">
              <Bot size={48} className="mb-2 opacity-50" />
              <Text type="secondary">{t("a2a.chat.emptyHistory")}</Text>
            </div>
          )}

          {messages.map((message) => (
            <div
              key={message.id}
              className={`flex ${
                message.role === "user" ? "justify-end" : "justify-start"
              }`}
            >
              <div
                className={`flex gap-2 max-w-[80%] ${
                  message.role === "user" ? "flex-row-reverse" : "flex-row"
                }`}
              >
                <div
                  className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
                    message.role === "user"
                      ? "bg-blue-500 text-white"
                      : "bg-green-500 text-white"
                  }`}
                >
                  {message.role === "user" ? (
                    <User size={16} />
                  ) : (
                    <Bot size={16} />
                  )}
                </div>
                <div>
                  <div
                    className={`px-4 py-2 rounded-lg ${
                      message.role === "user"
                        ? "bg-blue-500 text-white rounded-tr-none"
                        : "bg-gray-100 text-gray-800 rounded-tl-none"
                    }`}
                  >
                    <div className="text-sm whitespace-pre-wrap break-words">
                      {renderMessageContent(message.content)}
                    </div>
                  </div>
                  <Text
                    type="secondary"
                    className={`text-xs mt-1 block ${
                      message.role === "user" ? "text-right" : "text-left"
                    }`}
                  >
                    {formatTime(message.timestamp)}
                  </Text>
                </div>
              </div>
            </div>
          ))}

          {sending && (
            <div className="flex justify-start">
              <div className="flex gap-2">
                <div className="flex-shrink-0 w-8 h-8 rounded-full bg-green-500 text-white flex items-center justify-center">
                  <Bot size={16} />
                </div>
                <div className="px-4 py-2 rounded-lg bg-gray-100 rounded-tl-none">
                  <Loader2 size={16} className="animate-spin text-gray-400" />
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Area */}
        <div className="mt-4 pt-4 border-t">
          <div className="flex gap-2">
            <Input.TextArea
              placeholder={t("a2a.chat.placeholder")}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={2}
              autoSize={{ minRows: 2, maxRows: 4 }}
              disabled={sending || !agent.is_available}
            />
            <Button
              type="primary"
              icon={<Send size={16} />}
              onClick={handleSend}
              loading={sending}
              disabled={!inputValue.trim() || !agent.is_available}
              className="h-auto"
            >
              {t("a2a.chat.send")}
            </Button>
          </div>
          {!agent.is_available && (
            <Text type="secondary" className="text-xs mt-1 block">
              {t("a2a.chat.agentUnavailable")}
            </Text>
          )}
        </div>
      </div>
    </Modal>
  );
}
