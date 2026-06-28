"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Spin, Alert } from "antd";
import { useTranslation } from "react-i18next";

import { conversationService } from "@/services/conversationService";
import { ApiConversationDetail, ChatMessageType } from "@/types/chat";
import { formatConversationMessagesFromResponse } from "@/lib/chatMessageExtractor";
import { ChatStreamMain } from "@/app/chat/streaming/chatStreamMain";
import { ChatRightPanel } from "@/app/chat/components/chatRightPanel";
import "@/styles/chat.css";

type SharePayload = {
  share_id: string;
  title: string;
  snapshot: ApiConversationDetail & {
    conversation_title?: string;
  };
};

export default function ShareConversationPage() {
  const params = useParams<{ shareId: string }>();
  const shareId = params?.shareId;
  const { t } = useTranslation("common");
  const [payload, setPayload] = useState<SharePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedMessageId, setSelectedMessageId] = useState<
    string | undefined
  >();
  const [showRightPanel, setShowRightPanel] = useState(false);

  useEffect(() => {
    if (!shareId) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);

    conversationService
      .getShare(shareId, controller.signal)
      .then((data) => setPayload(data))
      .catch((err) => {
        if (controller.signal.aborted) return;
        setError(err?.message || "Failed to load share");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [shareId]);

  const messages = useMemo<ChatMessageType[]>(() => {
    const snapshot = payload?.snapshot;
    if (!snapshot?.message) return [];

    return formatConversationMessagesFromResponse(snapshot, t);
  }, [payload, t]);

  const title =
    payload?.snapshot?.conversation_title ||
    payload?.title ||
    t("chatInterface.sharedConversation", "Shared conversation");

  if (loading) {
    return (
      <div className="h-full w-full flex items-center justify-center bg-white">
        <Spin />
      </div>
    );
  }

  if (error || !payload) {
    return (
      <div className="h-full w-full flex items-center justify-center bg-white px-6">
        <Alert
          type="error"
          showIcon
          message={t(
            "chatInterface.shareLoadFailed",
            "Unable to open this shared conversation"
          )}
          description={error}
        />
      </div>
    );
  }

  return (
    <div className="h-full w-full bg-white overflow-hidden flex">
      <main className="flex-1 flex flex-col overflow-hidden">
        <div className="mx-auto w-full max-w-3xl px-4 pt-8 pb-4">
          <div className="border-b border-slate-200 pb-4">
            <h1 className="text-2xl font-semibold text-slate-950">{title}</h1>
            <div className="mt-2 text-xs text-slate-500">
              {t(
                "chatInterface.shareReadOnly",
                "Shared from Nexent. Read-only view."
              )}
            </div>
          </div>
        </div>

        <ChatStreamMain
          messages={messages}
          input=""
          isLoading={false}
          isStreaming={false}
          readOnly
          onInputChange={() => {}}
          onSend={() => {}}
          onStop={() => {}}
          onKeyDown={() => {}}
          selectedMessageId={selectedMessageId}
          onSelectMessage={(messageId) => {
            setSelectedMessageId(messageId);
            setShowRightPanel(true);
          }}
        />
      </main>

      <ChatRightPanel
        messages={messages}
        onImageError={() => {}}
        maxInitialImages={14}
        isVisible={showRightPanel}
        toggleRightPanel={() => setShowRightPanel((value) => !value)}
        selectedMessageId={selectedMessageId}
      />
    </div>
  );
}
