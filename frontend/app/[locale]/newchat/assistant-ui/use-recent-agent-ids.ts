// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useMemo } from "react";
import { useConversationAgentHistory } from "@/hooks/chat/useConversationAgentHistory";
import { useThreadAgentRegistryVersion } from "../adapter/thread-agent-registry";

/**
 * Agent ids ordered by recency: agents picked in this session (tracked by
 * the thread-agent registry's session storage) come first, then agents in
 * conversation-history order. Drives the top-bar agent selector and the
 * "new conversation" fallback target on the landing page.
 */
export function useRecentAgentIds(): number[] {
  const { data: conversations } = useConversationAgentHistory();
  // Re-read the session recency list whenever a new selection is registered
  // so the ordering updates immediately after picking an agent card.
  const registryVersion = useThreadAgentRegistryVersion();

  return useMemo(() => {
    const seen = new Set<number>();
    const ordered: number[] = [];
    for (const conversation of conversations ?? []) {
      const id = conversation.agent_id;
      if (typeof id === "number" && !seen.has(id)) {
        seen.add(id);
        ordered.push(id);
      }
    }
    try {
      const recent = JSON.parse(
        window.sessionStorage.getItem("nexent_recent_agent_ids") || "[]"
      );
      if (Array.isArray(recent)) {
        for (const id of recent) {
          if (typeof id === "number" && !seen.has(id)) {
            seen.add(id);
            ordered.unshift(id);
          }
        }
      }
    } catch {
      // ignore malformed session storage
    }
    // Referenced so the memo recomputes when a new selection is registered.
    void registryVersion;
    return ordered;
  }, [conversations, registryVersion]);
}
