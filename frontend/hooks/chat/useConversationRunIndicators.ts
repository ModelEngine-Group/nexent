// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useAui, useAuiEvent, useAuiState } from "@assistant-ui/react";

type RunState = "running" | "completed";
type Indicators = {
  running: ReadonlySet<string>;
  completed: Set<string>;
  acknowledge: (id: string) => void;
};

export const ConversationRunIndicatorsContext = createContext<Indicators>({
  running: new Set(),
  completed: new Set(),
  acknowledge: () => {},
});

/** Track actual owning-thread events for new runs and retries, including background runs. */
export function useConversationRunIndicators(
  serverConversationIds?: ReadonlyMap<string, string>
) {
  const aui = useAui();
  const runtime = aui.threads().__internal_getAssistantRuntime?.();
  const items = useAuiState((state) => state.threads.threadItems);
  const [states, setStates] = useState<Record<string, RunState>>({});
  const acknowledge = useCallback(
    (id: string) => {
      const localIds = aui
        .threads()
        .getState()
        .threadItems.filter(
          (row) =>
            row.id === id ||
            row.remoteId === id ||
            serverConversationIds?.get(row.id) === id
        )
        .map((row) => row.id);
      localIds.push(id);
      setStates((previous) => {
        if (!localIds.some((localId) => previous[localId] === "completed"))
          return previous;
        const next = { ...previous };
        for (const localId of localIds)
          if (next[localId] === "completed") delete next[localId];
        return next;
      });
    },
    [aui, serverConversationIds]
  );

  useAuiEvent({ scope: "*", event: "thread.runStart" }, ({ threadId }) => {
    setStates((previous) => ({ ...previous, [threadId]: "running" }));
  });
  useAuiEvent({ scope: "*", event: "thread.runEnd" }, ({ threadId }) => {
    const last = runtime?.threads.getById(threadId).getState().messages.at(-1);
    const completed =
      last?.role === "assistant" && last.status.type === "complete";
    setStates((previous) => {
      const next = { ...previous };
      if (completed) next[threadId] = "completed";
      else delete next[threadId];
      return next;
    });
  });
  useAuiEvent("threads.selectionChanged", ({ threadId }) =>
    acknowledge(threadId)
  );

  useEffect(() => {
    const viewed = (event: Event) => {
      if (!(event.target instanceof Element)) return;
      const content = event.target.closest<HTMLElement>(
        "[data-conversation-content]"
      );
      const id = aui.threads().getState().mainThreadId;
      if (content?.dataset.conversationContent === id) acknowledge(id);
    };
    document.addEventListener("click", viewed, true);
    document.addEventListener("keydown", viewed, true);
    return () => {
      document.removeEventListener("click", viewed, true);
      document.removeEventListener("keydown", viewed, true);
    };
  }, [aui, acknowledge]);

  return useMemo<Indicators>(() => {
    const running = new Set<string>();
    const completed = new Set<string>();
    for (const [id, state] of Object.entries(states)) {
      const target = state === "running" ? running : completed;
      target.add(id);
      const remoteId =
        serverConversationIds?.get(id) ??
        items.find((item) => item.id === id)?.remoteId;
      if (remoteId) target.add(remoteId);
    }
    return { running, completed, acknowledge };
  }, [states, items, acknowledge, serverConversationIds]);
}
