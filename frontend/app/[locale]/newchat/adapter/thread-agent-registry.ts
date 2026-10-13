"use client";

import { useMemo, useSyncExternalStore } from "react";
import type { AssistantRuntime } from "@assistant-ui/react";

// Tracks the agent binding of brand-new conversations that do not have a
// backend conversation_id (and therefore no agent_id in the conversation
// list) yet. Keyed by the assistant-ui thread id.
const overrides = new Map<string, number>();
const activityTimes = new Map<string, number>();
let version = 0;
const listeners = new Set<() => void>();

export function recordThreadActivity(threadId: string): void {
  activityTimes.set(threadId, Date.now());
}

export function setThreadAgentOverride(
  threadId: string,
  agentId: number
): void {
  if (!threadId || !Number.isInteger(agentId) || agentId <= 0) return;
  overrides.set(threadId, agentId);
  version += 1;
  listeners.forEach((listener) => listener());
}

export function resolveThreadAgentId(
  agentId: unknown,
  override?: number
): number | null {
  const numericId =
    typeof agentId === "number" || typeof agentId === "string"
      ? Number(agentId)
      : NaN;
  return Number.isInteger(numericId) && numericId > 0
    ? numericId
    : (override ?? null);
}

export async function startAgentConversation(
  runtime: AssistantRuntime,
  agentId: number
): Promise<void> {
  if (!Number.isInteger(agentId) || agentId <= 0) {
    throw new Error("Cannot start a conversation without a valid agent ID.");
  }

  await runtime.threads.switchToNewThread();
  const threadId = runtime.threads.getState().mainThreadId;
  const thread = runtime.threads.getItemById(threadId);
  await thread.initialize();
  await thread.updateCustom({ agentId });
  setThreadAgentOverride(threadId, agentId);
}

export async function resumeLatestAgentConversation(
  runtime: AssistantRuntime,
  agentId: number,
  generatedTitles?: ReadonlyMap<string, string>
): Promise<void> {
  if (!Number.isInteger(agentId) || agentId <= 0) {
    throw new Error("Cannot select a conversation without a valid agent ID.");
  }

  // Load older pages when this agent has no conversation in the visible page.
  while (true) {
    const state = runtime.threads.getState();
    const candidates = state.threadIds
      .map((id) => runtime.threads.getItemById(id).getState())
      .filter((item) => {
        const custom = item.custom as
          { agentId?: number | string; lastMessageAt?: string } | undefined;
        return (
          resolveThreadAgentId(custom?.agentId, overrides.get(item.id)) ===
            agentId &&
          (custom?.lastMessageAt ||
            item.isRunning ||
            generatedTitles?.has(item.id))
        );
      });
    candidates.sort((a, b) => {
      const activity = (item: (typeof candidates)[number]) => {
        const custom = item.custom as { lastMessageAt?: string } | undefined;
        if (item.isRunning) return Infinity;
        const timestamp = Date.parse(custom?.lastMessageAt ?? "");
        const recorded = activityTimes.get(item.id);
        if (recorded !== undefined) {
          return Math.max(recorded, Number.isFinite(timestamp) ? timestamp : 0);
        }
        return Number.isFinite(timestamp)
          ? timestamp
          : generatedTitles?.has(item.id)
            ? Infinity
            : 0;
      };
      return activity(b) - activity(a);
    });
    if (candidates[0]) {
      await runtime.threads.switchToThread(candidates[0].id);
      return;
    }
    if (!state.hasMore) break;
    const count = state.threadIds.length;
    await runtime.threads.loadMore();
    if (runtime.threads.getState().threadIds.length === count) break;
  }
  await startAgentConversation(runtime, agentId);
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
