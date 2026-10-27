// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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
import type { ApiConversationDetail as NewChatApiConversationDetail } from "@/types/conversation";
import { createShareThreadListAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";
import { ReadOnlyConversation } from "@/app/newchat/assistant-ui/thread";
import { compositeAttachmentAdapter } from "@/app/newchat/adapter/attachment-adapter";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { Agent } from "@/types/agentConfig";

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

function NewChatShareView({
  payload,
  title,
}: {
  payload: SharePayload;
  title: string;
}) {
  const adapter = useMemo(
    () => createShareThreadListAdapter(payload.snapshot),
    [payload.snapshot]
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
        setError(err?.message || t("chatInterface.shareLoadFailed"));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [shareId, t]);

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
          title={t(
            "chatInterface.shareLoadFailed",
            "Unable to open this shared conversation"
          )}
          description={error}
        />
      </div>
    );
  }

  return <NewChatShareView payload={payload} title={title} />;
}
