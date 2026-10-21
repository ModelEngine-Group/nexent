// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useState } from "react";

import { searchAgentInfo } from "@/services/agentConfigService";
import { useAgentStore } from "@/stores/agentStore";

/** Read back the persisted draft on entry, including Workbench's preloaded ID. */
export function useAgentEditorDraft(agentId: number) {
  const isValidAgentId = Number.isInteger(agentId) && agentId > 0;
  const [loadState, setLoadState] = useState({
    agentId,
    isLoading: isValidAgentId,
    error: null as Error | null,
  });
  if (!Object.is(loadState.agentId, agentId)) {
    setLoadState({ agentId, isLoading: isValidAgentId, error: null });
  }

  useEffect(() => {
    if (!isValidAgentId) return;
    let cancelled = false;
    const previousAgentId = useAgentStore.getState().currentAgentId;

    void (async () => {
      try {
        const saved = await useAgentStore.getState().waitForIdle();
        if (cancelled) return;
        if (!saved) throw new Error("Failed to save the Agent draft");

        const result = await searchAgentInfo(agentId, undefined, 0);
        if (cancelled) return;
        if (!result.success || !result.data) {
          throw new Error(result.message || "Failed to load the Agent draft");
        }
        const state = useAgentStore.getState();
        if (state.currentAgentId !== previousAgentId) {
          throw new Error("Agent context changed during synchronization");
        }
        if (Number(result.data.id) !== agentId) {
          throw new Error("Agent draft does not match the requested Agent");
        }
        if (state.currentAgentId === agentId) {
          if (!state.replaceServerSnapshot(agentId, result.data)) {
            throw new Error("Agent draft changed during synchronization");
          }
        } else {
          state.initialize(result.data);
        }
        setLoadState({ agentId, isLoading: false, error: null });
      } catch (requestError) {
        if (cancelled) return;
        setLoadState({
          agentId,
          isLoading: false,
          error:
            requestError instanceof Error
              ? requestError
              : new Error("Failed to load the Agent draft"),
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [agentId, isValidAgentId]);

  return { isLoading: loadState.isLoading, error: loadState.error };
}
