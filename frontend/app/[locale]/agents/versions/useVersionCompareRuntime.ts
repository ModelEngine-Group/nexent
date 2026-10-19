"use client";

import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";
import {
  useLocalRuntime,
  type AssistantRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";
import log from "@/lib/logger";

export function createVersionCompareAdapter(
  agentId: number | null | undefined,
  versionNo: number | null
): ChatModelAdapter {
  return {
    run(options) {
      if (!agentId || versionNo === null) {
        throw new Error("An Agent and version are required for comparison");
      }
      const run = remoteChatModelAdapter.run({
        ...options,
        runConfig: {
          ...options.runConfig,
          custom: {
            ...options.runConfig?.custom,
            runtimeMode: "agent-debug",
            agentId,
            agentVersionNo: versionNo,
          },
        },
      });
      return (async function* () {
        try {
          if ("then" in run) yield await run;
          else yield* run;
        } catch (error) {
          if (options.abortSignal.aborted) return;
          const message =
            error instanceof Error ? error.message : String(error);
          log.error("Version comparison failed", error);
          yield {
            status: {
              type: "incomplete" as const,
              reason: "error" as const,
              error: message,
            },
          };
        }
      })();
    },
  };
}

function useIsRunning(runtime: AssistantRuntime) {
  return useSyncExternalStore(
    runtime.thread.subscribe,
    () => runtime.thread.getState().isRunning,
    () => false
  );
}

function useIsLoading(runtime: AssistantRuntime) {
  return useSyncExternalStore(
    runtime.thread.subscribe,
    () => runtime.thread.getState().isLoading,
    () => true
  );
}

export function useVersionCompareRuntime({
  agentId,
  leftVersionNo,
  rightVersionNo,
  open,
}: {
  agentId?: number | null;
  leftVersionNo: number | null;
  rightVersionNo: number | null;
  open: boolean;
}) {
  const leftAdapter = useMemo(
    () => createVersionCompareAdapter(agentId, leftVersionNo),
    [agentId, leftVersionNo]
  );
  const rightAdapter = useMemo(
    () => createVersionCompareAdapter(agentId, rightVersionNo),
    [agentId, rightVersionNo]
  );
  const leftRuntime = useLocalRuntime(leftAdapter);
  const rightRuntime = useLocalRuntime(rightAdapter);
  const leftRunning = useIsRunning(leftRuntime);
  const rightRunning = useIsRunning(rightRuntime);
  const leftLoading = useIsLoading(leftRuntime);
  const rightLoading = useIsLoading(rightRuntime);
  const storageKey = `agent-version-compare:v2:${agentId}:${leftVersionNo}:${rightVersionNo}`;

  const stopCompare = useCallback(() => {
    if (!leftRuntime.thread.getState().isLoading)
      leftRuntime.thread.cancelRun();
    if (!rightRuntime.thread.getState().isLoading)
      rightRuntime.thread.cancelRun();
  }, [leftRuntime, rightRuntime]);

  const resetCompareState = useCallback(() => {
    stopCompare();
    if (!leftRuntime.thread.getState().isLoading) leftRuntime.thread.reset();
    if (!rightRuntime.thread.getState().isLoading) rightRuntime.thread.reset();
  }, [leftRuntime, rightRuntime, stopCompare]);

  useEffect(() => {
    if (leftLoading || rightLoading) return;
    resetCompareState();
    if (!open || !agentId || leftVersionNo === null || rightVersionNo === null)
      return;

    try {
      const stored = localStorage.getItem(storageKey);
      if (stored) {
        const session = JSON.parse(stored);
        leftRuntime.thread.import(session.left);
        rightRuntime.thread.import(session.right);
      }
    } catch (error) {
      resetCompareState();
      log.warn("Unable to restore version comparison", error);
    }

    const persist = () => {
      // Persist settled turns only; an interrupted run must not be restored as active.
      if (
        leftRuntime.thread.getState().isRunning ||
        rightRuntime.thread.getState().isRunning
      )
        return;
      try {
        localStorage.setItem(
          storageKey,
          JSON.stringify({
            left: leftRuntime.thread.export(),
            right: rightRuntime.thread.export(),
          })
        );
      } catch (error) {
        log.warn("Unable to persist version comparison", error);
      }
    };
    const unsubscribeLeft = leftRuntime.thread.subscribe(persist);
    const unsubscribeRight = rightRuntime.thread.subscribe(persist);
    return () => {
      unsubscribeLeft();
      unsubscribeRight();
      stopCompare();
      persist();
    };
  }, [
    open,
    leftLoading,
    rightLoading,
    agentId,
    leftVersionNo,
    rightVersionNo,
    storageKey,
    leftRuntime,
    rightRuntime,
    resetCompareState,
    stopCompare,
  ]);

  const runCompare = useCallback(
    (question: string) => {
      const text = question.trim();
      if (
        !open ||
        !agentId ||
        !text ||
        leftVersionNo === null ||
        rightVersionNo === null ||
        leftVersionNo === rightVersionNo
      )
        return;
      if (
        leftRuntime.thread.getState().isLoading ||
        rightRuntime.thread.getState().isLoading ||
        leftRuntime.thread.getState().isRunning ||
        rightRuntime.thread.getState().isRunning
      )
        return;
      for (const runtime of [leftRuntime, rightRuntime]) {
        runtime.thread.append({
          role: "user",
          content: [{ type: "text", text }],
        });
      }
    },
    [open, agentId, leftVersionNo, rightVersionNo, leftRuntime, rightRuntime]
  );

  return {
    leftRuntime,
    rightRuntime,
    isCompareStreaming: leftRunning || rightRunning,
    runCompare,
    stopCompare,
    resetCompareState,
  };
}
