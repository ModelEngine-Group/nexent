"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Spin, Alert } from "antd";
import { useTranslation } from "react-i18next";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  useRemoteThreadListRuntime,
  type AssistantRuntime,
} from "@assistant-ui/react";

import { conversationService } from "@/services/conversationService";
import type {
  ApiConversationDetail as LegacyApiConversationDetail,
  ChatMessageType,
} from "@/types/chat";
import type { ApiConversationDetail as NewChatApiConversationDetail } from "@/types/conversation";
import { formatConversationMessagesFromResponse } from "@/lib/chatMessageExtractor";
import { ChatStreamMain } from "@/app/chat/streaming/chatStreamMain";
import { ChatRightPanel } from "@/app/chat/components/chatRightPanel";
import { createShareThreadListAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";
import { ReadOnlyConversation } from "@/app/newchat/assistant-ui/thread";
import { compositeAttachmentAdapter } from "@/app/newchat/adapter/attachment-adapter";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { Agent } from "@/types/agentConfig";
import "@/styles/chat.css";

type SharePayload = {
  share_id: string;
  title: string;
  render_version?: "legacy" | "newchat";
  snapshot: NewChatApiConversationDetail & {
    conversation_title?: string;
  };
};

const sharedAgent = {
  id: "shared-agent",
  name: "Nexent",
  display_name: "Nexent",
} as unknown as Agent;

const useReadOnlyShareRuntime = (): AssistantRuntime =>
  useLocalRuntime(remoteChatModelAdapter, {
    adapters: {
      attachments: compositeAttachmentAdapter,
    },
  });

function NewChatShareView({ payload, title }: { payload: SharePayload; title: string }) {
  const adapter = useMemo(
    () => createShareThreadListAdapter(payload.snapshot),
    [payload.snapshot],
  );
  const runtime = useRemoteThreadListRuntime({
    runtimeHook: useReadOnlyShareRuntime,
    adapter,
    threadId: String(payload.snapshot.conversation_id),
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <ReadOnlyConversation agent={sharedAgent} title={title} />
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
}

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

    return formatConversationMessagesFromResponse(
      snapshot as unknown as LegacyApiConversationDetail,
      t,
    );
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

  if (payload.render_version === "newchat") {
    return <NewChatShareView payload={payload} title={title} />;
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
