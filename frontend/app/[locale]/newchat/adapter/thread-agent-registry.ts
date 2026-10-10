"use client";

import { useMemo, useSyncExternalStore } from "react";

// Tracks the agent binding of brand-new conversations that do not have a
// backend conversation_id (and therefore no agent_id in the conversation
// list) yet. Keyed by the assistant-ui thread id.
const overrides = new Map<string, number>();
let version = 0;
const listeners = new Set<() => void>();

export function setThreadAgentOverride(
  threadId: string,
  agentId: number
): void {
  if (!threadId || !Number.isInteger(agentId) || agentId <= 0) return;
  overrides.set(threadId, agentId);
  version += 1;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): number {
  return version;
}

function getServerSnapshot(): number {
  return 0;
}

export function useThreadAgentOverrides(): Record<string, number> {
  const versionSnapshot = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getServerSnapshot
  );
  return useMemo(
    () => Object.fromEntries(overrides),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [versionSnapshot]
  );
}

/** Bumps whenever an agent selection is registered — cheap change signal. */
export function useThreadAgentRegistryVersion(): number {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
