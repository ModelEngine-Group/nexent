// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { message } from "antd";
import type { ThreadMessage } from "@assistant-ui/react";
import { conversationService } from "@/services/conversationService";
import { configService } from "@/services/configService";
import { copyToClipboard } from "@/lib/clipboard";
import { useConversationShareRequest } from "@/stores/conversationShare";
import { collapseRefreshUserMessages } from "../adapter/history-branching";

interface ShareOptions {
  conversationId?: number;
  threadId?: string;
  messages: readonly Pick<ThreadMessage, "id" | "role">[];
  isRunning: boolean;
  isLoading: boolean;
  readOnly: boolean;
}

export function useConversationShare({
  conversationId,
  threadId,
  messages,
  isRunning,
  isLoading,
  readOnly,
}: ShareOptions) {
  const { t, i18n } = useTranslation();
  const [isShareMode, setIsShareMode] = useState(false);
  const [selectedShareMessageIds, setSelectedShareMessageIds] = useState(
    new Set<number>()
  );
  const [backendMessageIdsByAuiId, setBackendMessageIdsByAuiId] = useState(
    new Map<string, number>()
  );
  const [isCreatingShare, setIsCreatingShare] = useState(false);
  const [isLoadingShare, setIsLoadingShare] = useState(false);
  const [manualShareUrl, setManualShareUrl] = useState<string | null>(null);
  const request = useConversationShareRequest((state) => state.request);
  const setRequest = useConversationShareRequest((state) => state.setRequest);
  const generation = useRef(0);
  const busy = useRef(false);
  const disabled =
    !conversationId || isRunning || isLoading || readOnly || isLoadingShare;

  const leaveShareMode = useCallback(() => {
    generation.current++;
    setIsShareMode(false);
    setSelectedShareMessageIds(new Set());
    setBackendMessageIdsByAuiId(new Map());
    setIsLoadingShare(false);
  }, []);

  useEffect(() => {
    const currentGeneration = generation;
    // The external runtime can replace the active thread without unmounting us.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    leaveShareMode();
    setManualShareUrl(null);
    return () => {
      currentGeneration.current++;
      if (
        useConversationShareRequest.getState().request?.threadId === threadId
      ) {
        useConversationShareRequest.getState().setRequest(null);
      }
    };
  }, [conversationId, threadId, leaveShareMode]);

  const enterShareMode = useCallback(
    async (assistantMessageId?: string) => {
      if (disabled) return;
      const version = ++generation.current;
      setIsLoadingShare(true);
      try {
        const users = messages.filter((item) => item.role === "user");
        const targetIndex =
          assistantMessageId === undefined
            ? -1
            : messages.findIndex((item) => item.id === assistantMessageId);
        const targetUser =
          targetIndex < 0
            ? undefined
            : messages
                .slice(0, targetIndex)
                .findLast((item) => item.role === "user");
        if (!users.length || (assistantMessageId !== undefined && !targetUser))
          throw new Error("Missing share turn");
        let ids = new Map(users.map((item) => [item.id, Number(item.id)]));
        if (
          ![...ids.values()].every((id) => Number.isSafeInteger(id) && id > 0)
        ) {
          const response = await conversationService.getDetail(conversationId!);
          const backendUsers = collapseRefreshUserMessages(
            response.data?.[0]?.message ?? []
          ).filter((item) => item.role === "user");
          // Refuse ambiguous positional mapping, including regenerated user rows.
          if (backendUsers.length !== users.length)
            throw new Error("Ambiguous share message identities");
          ids = new Map(
            users.map((item, index) => [
              item.id,
              Number(backendUsers[index].message_id),
            ])
          );
        }
        if (
          ![...ids.values()].every(
            (id) => Number.isSafeInteger(id) && id > 0
          ) ||
          new Set(ids.values()).size !== users.length
        ) {
          throw new Error("Invalid share message identities");
        }
        if (generation.current !== version) return;
        setBackendMessageIdsByAuiId(ids);
        setSelectedShareMessageIds(
          new Set(targetUser ? [ids.get(targetUser.id)!] : ids.values())
        );
        setIsShareMode(true);
      } catch {
        if (generation.current === version)
          message.error(t("chatInterface.shareCreateFailed"));
      } finally {
        if (generation.current === version) setIsLoadingShare(false);
      }
    },
    [conversationId, disabled, messages, t]
  );

  useEffect(() => {
    if (
      !request ||
      request.threadId !== threadId ||
      request.conversationId !== conversationId ||
      disabled ||
      !messages.length
    )
      return;
    setRequest(null);
    // Synchronize a sidebar operation after its remote thread has finished loading.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void enterShareMode();
  }, [
    request,
    threadId,
    conversationId,
    disabled,
    messages.length,
    setRequest,
    enterShareMode,
  ]);

  const toggleShareMessage = useCallback((id: number) => {
    setSelectedShareMessageIds((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);
  const toggleShareAll = useCallback(() => {
    setSelectedShareMessageIds((previous) =>
      previous.size === backendMessageIdsByAuiId.size
        ? new Set()
        : new Set(backendMessageIdsByAuiId.values())
    );
  }, [backendMessageIdsByAuiId]);

  const createShare = useCallback(async () => {
    if (
      !conversationId ||
      !selectedShareMessageIds.size ||
      busy.current ||
      isRunning ||
      readOnly
    )
      return;
    busy.current = true;
    const version = generation.current;
    setIsCreatingShare(true);
    try {
      const result = await conversationService.createShare({
        conversationId,
        mode: "selected",
        selected_user_message_ids: Array.from(selectedShareMessageIds),
        render_version: "newchat",
      });
      const runtimeConfig = await configService
        .fetchRuntimeFrontendConfig()
        .catch((): { shareBaseUrl?: string } => ({}));
      if (generation.current !== version) return;
      const baseUrl = (
        runtimeConfig.shareBaseUrl ||
        process.env.NEXT_PUBLIC_SHARE_BASE_URL ||
        window.location.origin
      ).replace(/\/$/, "");
      const locale = i18n.resolvedLanguage || i18n.language || "zh";
      const shareUrl = `${baseUrl}/${locale}/share/${result.share_id}`;
      try {
        await copyToClipboard(shareUrl);
        if (generation.current === version)
          message.success(t("chatInterface.shareLinkCopied"));
      } catch {
        if (generation.current === version) setManualShareUrl(shareUrl);
      }
      if (generation.current === version) leaveShareMode();
    } catch {
      if (generation.current === version)
        message.error(t("chatInterface.shareCreateFailed"));
    } finally {
      busy.current = false;
      setIsCreatingShare(false);
    }
  }, [
    conversationId,
    selectedShareMessageIds,
    isRunning,
    readOnly,
    i18n,
    leaveShareMode,
    t,
  ]);

  return {
    isShareMode,
    selectedShareMessageIds,
    backendMessageIdsByAuiId,
    isCreatingShare,
    isLoadingShare,
    manualShareUrl,
    setManualShareUrl,
    enterShareMode,
    leaveShareMode,
    toggleShareMessage,
    toggleShareAll,
    createShare,
    disabled,
  };
}
