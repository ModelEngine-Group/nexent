// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, type RefObject } from "react";
import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import { CONVERSATION_SYNC_FRESHNESS_MS } from "@/const/conversationSync";
import log from "@/lib/logger";

/** Resume cross-window sync once, without refreshing on ordinary page clicks. */
export function useForegroundRefresh(
  queryKey: QueryKey,
  enabled: boolean,
  paused?: RefObject<boolean>
) {
  const client = useQueryClient();
  useEffect(() => {
    if (!enabled) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = () => {
      if (
        document.visibilityState !== "visible" ||
        !navigator.onLine ||
        timer !== undefined ||
        paused?.current
      )
        return;
      const updated = client.getQueryState(queryKey)?.dataUpdatedAt ?? 0;
      const delay = Math.max(
        0,
        CONVERSATION_SYNC_FRESHNESS_MS - (Date.now() - updated)
      );
      timer = setTimeout(() => {
        timer = undefined;
        if (
          document.visibilityState !== "visible" ||
          !navigator.onLine ||
          paused?.current
        )
          return;
        void client
          .fetchQuery({ queryKey, staleTime: CONVERSATION_SYNC_FRESHNESS_MS })
          .catch((error: unknown) =>
            log.warn("Failed to refresh foreground conversations", error)
          );
      }, delay + 1);
    };
    window.addEventListener("focus", refresh);
    window.addEventListener("online", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      if (timer !== undefined) clearTimeout(timer);
      window.removeEventListener("focus", refresh);
      window.removeEventListener("online", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [client, enabled, queryKey, paused]);
}
