// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useRef } from "react";
import { useAui, useAuiState } from "@assistant-ui/react";
import log from "@/lib/logger";
import { usePinnedThreads } from "./thread-pins";

/** Refresh missing metadata without switching the active conversation runtime. */
export function WorkbenchPinHistorySync() {
  const aui = useAui();
  const pins = usePinnedThreads();
  const threadIds = useAuiState((state) => state.threads.threadIds);
  const items = useAuiState((state) => state.threads.threadItems);
  const busy = useAuiState(
    (state) => state.threads.isLoading || state.threads.isLoadingMore
  );
  const attempted = useRef<number | undefined>(undefined);
  const snapshot = pins?.serverPins;
  const revision = pins?.serverPinsRevision;

  useEffect(() => {
    if (!snapshot || busy || revision === attempted.current) return;
    const listed = new Set(threadIds);
    const loaded = new Set(
      items.filter((item) => listed.has(item.id)).map((item) => item.remoteId)
    );
    if (snapshot.every((item) => loaded.has(String(item.conversation_id))))
      return;
    attempted.current = revision;
    void aui
      .threads()
      .reload()
      .catch((error: unknown) => {
        log.error("Failed to refresh missing Workbench pin histories", error);
      });
  }, [aui, snapshot, revision, items, threadIds, busy]);
  return null;
}
