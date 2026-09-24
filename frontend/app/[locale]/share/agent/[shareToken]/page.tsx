"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { Button, Spin } from "antd";
import { Send, Square } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/services/api";
import {
  buildAgentShareRunPayload,
  extractAgentShareHistory,
  getAgentShareFinalAnswerChunk,
  getAgentShareLoadAction,
  getAgentSharePageState,
  getAgentShareStreamError,
  parseAgentShareSseLine,
  type AgentShareChatMessage,
} from "@/lib/agentShareChat";
import {
  agentShareRuntimeService,
  type AgentShareMetadata,
} from "@/services/agentShareRuntimeService";

function createMessageId(role: AgentShareChatMessage["role"]): string {
  return `${role}-${crypto.randomUUID()}`;
}

export default function AgentSharePage() {
  const params = useParams<{ shareToken: string }>();
  const shareToken = params?.shareToken;
  const { isAuthenticated, isAuthChecking } = useAuthenticationContext();
  const { t } = useTranslation("common");
  const unavailableMessage = t(
    "agentSharePage.unavailable",
    "This Agent share is unavailable."
  );
  const streamControllerRef = useRef<AbortController | null>(null);
  const stoppedByUserRef = useRef(false);
  const [metadata, setMetadata] = useState<AgentShareMetadata | null>(null);
  const [messages, setMessages] = useState<AgentShareChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (
      getAgentShareLoadAction({
        shareToken,
        isAuthChecking,
        isAuthenticated,
      }) !== "load"
    ) {
      return;
    }

    const controller = new AbortController();
    setIsLoading(true);
    setError(null);
    Promise.all([
      agentShareRuntimeService.getMetadata(shareToken),
      agentShareRuntimeService.getHistory(shareToken),
    ])
      .then(([nextMetadata, history]) => {
        if (controller.signal.aborted) return;
        setMetadata(nextMetadata);
        setMessages(extractAgentShareHistory(history.history));
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(unavailableMessage);
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });

    return () => controller.abort();
  }, [isAuthenticated, isAuthChecking, shareToken, unavailableMessage]);

  useEffect(
    () => () => {
      streamControllerRef.current?.abort();
    },
    []
  );

  const displayMessages = useMemo(() => {
    if (messages.length || !metadata?.greeting_message) return messages;
    return [
      {
        id: "agent-greeting",
        role: "assistant" as const,
        content: metadata.greeting_message,
      },
    ];
  }, [messages, metadata?.greeting_message]);

  const appendToAssistant = useCallback(
    (assistantMessageId: string, content: string) => {
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantMessageId
            ? { ...message, content: `${message.content}${content}` }
            : message
        )
      );
    },
    []
  );

  const send = useCallback(async () => {
    const query = input.trim();
    if (!query || !shareToken || isStreaming) return;

    const userMessage: AgentShareChatMessage = {
      id: createMessageId("user"),
      role: "user",
      content: query,
    };
    const assistantMessageId = createMessageId("assistant");
    setInput("");
    setError(null);
    setMessages((current) => [
      ...current,
      userMessage,
      { id: assistantMessageId, role: "assistant", content: "" },
    ]);
    setIsStreaming(true);
    stoppedByUserRef.current = false;
    const controller = new AbortController();
    streamControllerRef.current = controller;
    let receivedAnswer = false;

    try {
      const reader = await agentShareRuntimeService.run(
        shareToken,
        buildAgentShareRunPayload(
          query,
          Intl.DateTimeFormat().resolvedOptions().timeZone
        ),
        controller.signal
      );
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          const event = parseAgentShareSseLine(line);
          if (!event) continue;
          const finalAnswer = getAgentShareFinalAnswerChunk(event);
          if (finalAnswer !== null) {
            receivedAnswer = true;
            appendToAssistant(assistantMessageId, finalAnswer);
          }
          const streamError = getAgentShareStreamError(event);
          if (streamError) setError(streamError);
        }
      }

      if (!receivedAnswer && !stoppedByUserRef.current) {
        setError(
          t(
            "agentSharePage.noAnswer",
            "The Agent did not return an answer. Please try again."
          )
        );
      }
    } catch (streamError) {
      if (!stoppedByUserRef.current && !controller.signal.aborted) {
        setError(
          streamError instanceof ApiError && Number(streamError.code) === 429
            ? t(
                "agentSharePage.rateLimited",
                "This Agent is receiving too many requests. Please try again shortly."
              )
            : t(
                "agentSharePage.runFailed",
                "Unable to run this Agent. Please try again."
              )
        );
      }
    } finally {
      if (streamControllerRef.current === controller) {
        streamControllerRef.current = null;
      }
      setIsStreaming(false);
    }
  }, [appendToAssistant, input, isStreaming, shareToken, t]);

  const stop = useCallback(async () => {
    if (!shareToken || !isStreaming) return;
    stoppedByUserRef.current = true;
    try {
      await agentShareRuntimeService.stop(shareToken);
    } catch {
      setError(
        t("agentSharePage.stopFailed", "Unable to stop this Agent response.")
      );
    } finally {
      streamControllerRef.current?.abort();
    }
  }, [isStreaming, shareToken, t]);

  const pageState = getAgentSharePageState({
    isAuthChecking,
    isAuthenticated,
    isLoading,
    hasMetadata: metadata !== null,
    hasUnavailableError: error === unavailableMessage,
  });

  if (pageState === "loading") {
    return (
      <div className="flex h-full w-full items-center justify-center bg-white">
        <Spin />
      </div>
    );
  }

  if (pageState === "unavailable" || !metadata) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-white px-6">
        <p className="text-sm text-slate-600">{unavailableMessage}</p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-white">
      <header className="mx-auto flex w-full max-w-3xl items-center gap-3 border-b border-slate-200 px-5 py-4">
        {metadata.icon_url ? (
          // The owner-configured icon is display-only metadata from the share API.
          <img
            src={metadata.icon_url}
            alt=""
            className="size-10 rounded-full object-cover"
          />
        ) : (
          <div className="flex size-10 items-center justify-center rounded-full bg-blue-100 text-sm font-semibold text-blue-700">
            {metadata.display_name.slice(0, 1).toUpperCase() || "A"}
          </div>
        )}
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold text-slate-950">
            {metadata.display_name}
          </h1>
          {metadata.description && (
            <p className="mt-0.5 line-clamp-2 text-sm text-slate-500">
              {metadata.description}
            </p>
          )}
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col overflow-y-auto px-5 py-6">
        <div
          className="space-y-4"
          role="log"
          aria-live="polite"
          aria-relevant="additions text"
        >
          {displayMessages.map((message) => (
            <div
              key={message.id}
              className={
                message.role === "user"
                  ? "ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-blue-600 px-4 py-2.5 text-sm whitespace-pre-wrap text-white"
                  : "mr-auto max-w-[85%] rounded-2xl rounded-bl-md bg-slate-100 px-4 py-2.5 text-sm whitespace-pre-wrap text-slate-800"
              }
            >
              {message.content || (isStreaming ? "…" : "")}
            </div>
          ))}
        </div>
        {error && (
          <p className="mt-4 text-sm text-red-600" role="alert">
            {error}
          </p>
        )}
      </main>

      <footer className="border-t border-slate-200 bg-white px-5 py-4">
        <div className="mx-auto flex w-full max-w-3xl items-end gap-3">
          <Textarea
            aria-label={t("agentSharePage.inputPlaceholder", "Ask a question")}
            value={input}
            disabled={isStreaming}
            placeholder={t("agentSharePage.inputPlaceholder", "Ask a question")}
            className="min-h-[48px] resize-none"
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
          />
          {isStreaming ? (
            <Button
              type="primary"
              danger
              shape="circle"
              aria-label={t("agentSharePage.stopResponse", "Stop response")}
              icon={<Square className="size-4" aria-hidden />}
              onClick={() => void stop()}
            />
          ) : (
            <Button
              type="primary"
              shape="circle"
              aria-label={t("agentSharePage.sendMessage", "Send message")}
              disabled={!input.trim()}
              icon={<Send className="size-4" aria-hidden />}
              onClick={() => void send()}
            />
          )}
        </div>
      </footer>
    </div>
  );
}
