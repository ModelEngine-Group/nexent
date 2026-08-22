"use client";

import { useNl2AgentFormLock } from "@/contexts/nl2AgentFlow";
import { useAgentStore } from "@/stores/agentStore";

export function useAgentReadOnly(): boolean {
  const permissionReadOnly = useAgentStore((state) => state.isReadOnly);
  const flowLocked = useNl2AgentFormLock();
  return permissionReadOnly || flowLocked;
}
