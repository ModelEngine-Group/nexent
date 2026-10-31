// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAui, useAuiEvent, useAuiState } from "@assistant-ui/react";
import { conversationService } from "@/services/conversationService";
import { getConversationDateBoundaries } from "@/lib/conversationViewport";
import type { ConversationListPage } from "@/types/conversation";
import log from "@/lib/logger";
import { useForegroundRefresh } from "./useForegroundRefresh";
import { CONVERSATION_SYNC_FRESHNESS_MS } from "@/const/conversationSync";

/** Observe Workbench's first page; reload metadata only when it changes. */
export function useConversationActivitySync(
  scopeKey: string | null,
  conversationType: "workbench" | "agent_chat"
) {
  const aui = useAui();
  const busy = useAuiState(
    (state) => state.threads.isLoading || state.threads.isLoadingMore
  );
  const [visible, setVisible] = useState(
    () =>
      typeof document !== "undefined" && document.visibilityState === "visible"
  );
  const applied = useRef<ConversationListPage | undefined>(undefined);
  const pending = useRef(false);
  const failures = useRef(0);
  const lifecycle = useRef({ active: true });
  useEffect(() => {
    const lifetime = { active: true };
    lifecycle.current = lifetime;
    failures.current = 0;
    return () => {
      lifetime.active = false;
    };
  }, [scopeKey, conversationType]);
  const queryKey = useMemo(
    () => ["conversation-activity", scopeKey, conversationType],
    [scopeKey, conversationType]
  );
  useForegroundRefresh(queryKey, Boolean(scopeKey));
  const query = useQuery({
    queryKey,
    staleTime: CONVERSATION_SYNC_FRESHNESS_MS,
    enabled: conversationType === "workbench" && Boolean(scopeKey) && visible,
    queryFn: async () => {
      const lifetime = lifecycle.current;
      try {
        const data = await conversationService.getList({
          offset: 0,
          limit: 30,
          conversationType,
          ...getConversationDateBoundaries(),
        });
        if (lifetime.active) failures.current = 0;
        return data;
      } catch (error) {
        if (lifetime.active) failures.current++;
        throw error;
      }
    },
    refetchInterval: () => Math.min(5_000 * 2 ** failures.current, 60_000),
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  });
  const refetch = query.refetch;
  useAuiEvent({ scope: "*", event: "thread.runEnd" }, () => {
    if (
      conversationType === "workbench" &&
      scopeKey &&
      document.visibilityState === "visible" &&
      navigator.onLine
    )
      void refetch({ cancelRefetch: false });
  });
  useEffect(() => {
    applied.current = undefined;
    const refresh = () => {
      const active = document.visibilityState === "visible";
      setVisible(active);
    };
    document.addEventListener("visibilitychange", refresh);
    return () => {
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [scopeKey, conversationType, refetch]);

  useEffect(() => {
    const data = query.data;
    if (
      !scopeKey ||
      !visible ||
      busy ||
      query.isFetching ||
      pending.current ||
      !data ||
      data === applied.current
    )
      return;
    const epoch = lifecycle.current;
    const isCurrent = () => {
      const state = aui.threads().getState();
      const listed = new Set(state.threadIds);
      const items = state.threadItems.filter((item) => listed.has(item.id));
      return (
        items.filter((item) => item.remoteId && /^\d+$/.test(item.remoteId))
          .length <= data.metadata.total &&
        data.items.every((row) => {
          const timestamp = row.last_activity_time ?? row.create_time;
          const expectedActivity = timestamp
            ? new Date(timestamp).toISOString()
            : undefined;
          return items.some(
            (item) =>
              item.remoteId === String(row.conversation_id) &&
              item.title ===
                (row.conversation_title ?? "Untitled conversation") &&
              ((item.custom as { agentId?: number } | undefined)?.agentId ??
                null) === (row.agent_id ?? null) &&
              (item.custom as { lastMessageAt?: string } | undefined)
                ?.lastMessageAt === expectedActivity
          );
        })
      );
    };
    if (isCurrent()) {
      applied.current = data;
      return;
    }
    pending.current = true;
    // Same-adapter list reload preserves the active thread runtime, including
    // drafts, attachments, resources and an in-flight stream.
    void aui
      .threads()
      .reload()
      .then(() => {
        if (!epoch.active) return;
        if (isCurrent()) applied.current = data;
      })
      .catch((error: unknown) => {
        log.warn("Failed to refresh conversation activity", error);
      })
      .finally(() => {
        pending.current = false;
      });
  }, [
    aui,
    busy,
    query.data,
    query.dataUpdatedAt,
    query.isFetching,
    scopeKey,
    visible,
  ]);
}
