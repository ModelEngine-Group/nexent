"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { AssistantRuntime } from "@assistant-ui/react";
import type { HumanInteractionController } from "./useHumanInteractionController";
import { humanInteractionClient, HumanInteractionHttpError } from "./client";
import {
  EMPTY_RUN_MESSAGE,
  canAutoSendQueuedMessage,
  reduceRunMessage,
  type RunMessageAction,
  type RunMessageState,
} from "./runMessageQueue";

export function useRunMessageQueue({
  scope,
  runtime,
  controller,
}: {
  scope: string;
  runtime: AssistantRuntime;
  controller: HumanInteractionController;
}) {
  const states = useRef(new Map<string, RunMessageState>());
  const [, render] = useState(0);
  const activeScope = useRef(scope);
  activeScope.current = scope;
  const state = states.current.get(scope) ?? EMPTY_RUN_MESSAGE;
  const active = controller.active || controller.streaming;
  const update = useCallback(
    (action: RunMessageAction, target = scope) => {
      const previous = states.current.get(target) ?? EMPTY_RUN_MESSAGE;
      const next = reduceRunMessage(previous, action);
      if (next !== previous) {
        states.current.set(target, next);
        render((value) => value + 1);
      }
    },
    [scope]
  );

  const enqueue = useCallback(
    (text: string) => {
      if (!active || !text.trim() || text.length > 8000) return false;
      const previous = states.current.get(scope) ?? EMPTY_RUN_MESSAGE;
      if (previous.used || previous.entry) return false;
      update({
        type: "enqueue",
        entry: {
          id: crypto.randomUUID(),
          text: text.trim(),
          status: "queued",
          runId: controller.active ? (controller.run?.run_id ?? null) : null,
          previousRunId: controller.active
            ? null
            : (controller.run?.run_id ?? null),
          durable: controller.available,
        },
      });
      return true;
    },
    [
      active,
      controller.active,
      controller.available,
      controller.run?.run_id,
      scope,
      update,
    ]
  );

  useEffect(() => {
    if (controller.run && state.entry && !state.entry.runId) {
      update({ type: "bind", runId: controller.run.run_id });
    }
    if (!active) update({ type: "idle" });
  }, [active, controller.run, state.entry, update]);

  const sendNext = useCallback(() => {
    const entry = states.current.get(scope)?.entry;
    if (
      !entry ||
      !["queued", "error"].includes(entry.status) ||
      active ||
      runtime.thread.getState().isRunning
    )
      return;
    update({ type: "deliver" });
    try {
      // Use the existing normal-turn path and its selected Agent/run configuration.
      runtime.thread.composer.setText(entry.text);
      runtime.thread.composer.send();
      update({ type: "sent" });
    } catch (error) {
      update({
        type: "error",
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }, [active, runtime, scope, update]);

  const guide = useCallback(async () => {
    const entry = states.current.get(scope)?.entry;
    const run = controller.run;
    if (
      !entry ||
      !["queued", "error", "uncertain"].includes(entry.status) ||
      !entry.runId ||
      run?.run_id !== entry.runId ||
      (!controller.active && entry.status !== "uncertain")
    )
      return;
    update({ type: "deliver" });
    try {
      await humanInteractionClient.steer(entry.runId, entry.id, entry.text);
    } catch (error) {
      update(
        {
          type: "error",
          messageId: entry.id,
          uncertain:
            !(error instanceof HumanInteractionHttpError) ||
            error.status >= 500,
          error: error instanceof Error ? error.message : String(error),
        },
        scope
      );
      return;
    }
    // Acceptance releases the composer immediately, even before the loop consumes
    // the guidance. A later refresh cannot turn an accepted message into a retry.
    update({ type: "guided", messageId: entry.id }, scope);
    if (activeScope.current === scope) {
      const latest = await controller.refresh();
      if (
        activeScope.current === scope &&
        latest?.run_id === entry.runId &&
        ["READY", "RUNNING"].includes(latest.status) &&
        !runtime.thread.getState().isRunning
      ) {
        controller.reconnect();
      }
    }
  }, [controller, runtime, scope, update]);

  useEffect(() => {
    const lastMessage = runtime.thread.getState().messages.at(-1);
    const completed =
      lastMessage?.role === "assistant" &&
      lastMessage.status?.type === "complete";
    if (
      canAutoSendQueuedMessage(
        state.entry,
        controller.run,
        controller.streaming,
        completed
      )
    )
      sendNext();
  }, [controller.run, controller.streaming, runtime, sendNext, state.entry]);

  return {
    ...state,
    scope,
    error: controller.error,
    active,
    enqueue,
    guide,
    sendNext,
    update,
    canGuide: Boolean(
      (controller.active || state.entry?.status === "uncertain") &&
      state.entry?.runId === controller.run?.run_id &&
      (state.entry?.status === "uncertain" ||
        ["READY", "RUNNING", "WAITING_HUMAN"].includes(
          controller.run?.status ?? ""
        ))
    ),
    canStop: controller.active,
    stop: () => controller.control("terminate"),
  };
}

export type RunMessageQueueController = ReturnType<typeof useRunMessageQueue>;
export const RunMessageQueueContext =
  createContext<RunMessageQueueController | null>(null);
export const useRunMessageQueueContext = () =>
  useContext(RunMessageQueueContext);
