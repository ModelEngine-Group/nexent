// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useMemo, useRef } from "react";
import { useAui, useAuiEvent, useAuiState } from "@assistant-ui/react";
import log from "@/lib/logger";

interface ConfirmedHistoryChanges {
  serverConversationIds?: ReadonlyMap<string, string>;
  generatedTitles?: ReadonlyMap<string, string>;
}
interface RefreshQueue {
  request: (operation: boolean) => void;
  observe: (revision: string) => void;
  flush: () => void;
}

/** Initial loading belongs to the runtime adapter; refresh only on real events. */
export function useConversationActivitySync(
  scopeKey: string | null,
  conversationType: "workbench" | "agent_chat",
  { serverConversationIds, generatedTitles }: ConfirmedHistoryChanges = {}
) {
  const aui = useAui();
  const busy = useAuiState(
    (state) => state.threads.isLoading || state.threads.isLoadingMore
  );
  const queue = useRef<RefreshQueue | undefined>(undefined);
  const revision = useMemo(
    () =>
      JSON.stringify([
        [...(serverConversationIds ?? [])]
          .filter(
            ([, id]) =>
              /^\d+$/.test(id) &&
              Number.isSafeInteger(Number(id)) &&
              Number(id) > 0
          )
          .sort(([a], [b]) => a.localeCompare(b)),
        [...(generatedTitles ?? [])].sort(([a], [b]) => a.localeCompare(b)),
      ]),
    [serverConversationIds, generatedTitles]
  );

  useEffect(() => {
    if (!scopeKey || conversationType !== "workbench") return;
    let active = true;
    let pending = false;
    let dirty = false;
    let previousRevision: string | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const available = () =>
      active && document.visibilityState === "visible" && navigator.onLine;
    const isBusy = () => {
      const threads = aui.threads().getState();
      return threads.isLoading || threads.isLoadingMore;
    };
    const flush = () => {
      if (!dirty || pending || timer !== undefined || !available() || isBusy())
        return;
      // Coalesce focus/visibility/reconnect and confirmed changes in one burst.
      // This timer is one-shot: idle pages and failures never schedule polling.
      timer = setTimeout(() => {
        timer = undefined;
        if (!dirty || pending || !available() || isBusy()) return;
        dirty = false;
        pending = true;
        void (async () => {
          try {
            // The adapter reloads the loaded range, preserving the active runtime.
            await aui.threads().reload();
          } catch (error) {
            if (active)
              log.warn("Failed to refresh conversation history", error);
          } finally {
            pending = false;
            if (active) flush();
          }
        })();
      }, 50);
    };
    const current: RefreshQueue = {
      request(operation) {
        if (!active || (!operation && pending)) return;
        dirty = true;
        flush();
      },
      observe(next) {
        const changed =
          previousRevision !== undefined && previousRevision !== next;
        previousRevision = next;
        if (changed) current.request(true);
      },
      flush,
    };
    queue.current = current;
    const foreground = () => {
      if (available()) current.request(false);
    };
    window.addEventListener("focus", foreground);
    window.addEventListener("online", foreground);
    document.addEventListener("visibilitychange", foreground);
    return () => {
      active = false;
      dirty = false;
      if (timer !== undefined) clearTimeout(timer);
      if (queue.current === current) queue.current = undefined;
      window.removeEventListener("focus", foreground);
      window.removeEventListener("online", foreground);
      document.removeEventListener("visibilitychange", foreground);
    };
  }, [aui, scopeKey, conversationType]);

  useEffect(() => {
    queue.current?.observe(revision);
  }, [revision, scopeKey, conversationType]);
  useEffect(() => {
    queue.current?.flush();
  }, [busy]);
  useAuiEvent({ scope: "*", event: "thread.runEnd" }, () => {
    queue.current?.request(true);
  });
}
