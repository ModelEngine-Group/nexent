"use client";

import { useNl2AgentFormLock } from "@/contexts/nl2AgentFlow";
import { useAgentConfigStore } from "@/stores/agentConfigStore";

export function useAgentReadOnly(): boolean {
  const permissionReadOnly = useAgentConfigStore((state) => state.isReadOnly());
  const flowLocked = useNl2AgentFormLock();
  return permissionReadOnly || flowLocked;
}
