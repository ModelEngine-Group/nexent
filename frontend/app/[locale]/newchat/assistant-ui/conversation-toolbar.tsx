// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App, Button } from "antd";
import { Copy } from "lucide-react";
import { useTranslation } from "react-i18next";
import { copyToClipboard } from "@/lib/clipboard";
import { ConversationArtifactsToolbarEntry } from "../ui/artifacts-panel";

export function ConversationToolbar({
  conversationId,
}: {
  conversationId?: number;
}) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  if (
    conversationId === undefined ||
    !Number.isSafeInteger(conversationId) ||
    conversationId < 1
  ) {
    return <ConversationArtifactsToolbarEntry />;
  }

  const id = String(conversationId);
  const label = t("chat.thread.conversationId");
  const copyLabel = t("chat.thread.copyConversationId", { id });
  const handleCopy = async () => {
    try {
      await copyToClipboard(id);
      void message.success(t("chat.thread.conversationIdCopied"));
    } catch {
      void message.error(t("chat.thread.conversationIdCopyFailed"));
    }
  };

  return (
    <div className="flex min-h-12 shrink-0 flex-wrap items-center justify-end gap-x-3 px-4">
      <Button
        type="text"
        size="small"
        className="max-w-full min-w-0 !text-xs !text-[var(--color-text-secondary)]"
        aria-label={copyLabel}
        title={copyLabel}
        onClick={handleCopy}
      >
        <span className="truncate">
          {label}: <span className="font-mono">{id}</span>
        </span>
        <Copy size={14} aria-hidden="true" className="shrink-0" />
      </Button>
      <ConversationArtifactsToolbarEntry className="!px-0" />
    </div>
  );
}
