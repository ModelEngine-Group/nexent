"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  humanInteractionClient,
  type HumanDecision,
  type HumanRequest,
  type HumanRun,
} from "./client";
import type { HumanClarificationAnswer } from "./clarification";

const ACTIVE_STATUSES = new Set([
  "INITIALIZING",
  "READY",
  "RUNNING",
  "WAITING_HUMAN",
  "RECOVERY_REQUIRED",
]);
const STREAM_RECONNECT_STATUSES = new Set(["READY", "RUNNING"]);

export interface HumanInteractionController {
  available: boolean;
  run: HumanRun | null;
  active: boolean;
  pending: boolean;
  streaming: boolean;
  error: string;
  busy: boolean;
  control: (action: "pause" | "terminate") => Promise<void>;
  reconnect: () => void;
  decide: (
    item: HumanRequest,
    decision: HumanDecision,
    response: string | HumanClarificationAnswer[]
  ) => Promise<void>;
  refresh: () => Promise<HumanRun | null>;
}

export function useHumanInteractionController({
  conversationId,
  onEnabledChange,
  isRunning,
  onContinue,
}: {
  conversationId?: number;
  onEnabledChange: (enabled: boolean) => void;
  isRunning: boolean;
  onContinue: (runId: string, after: number) => void;
}): HumanInteractionController {
  const [available, setAvailable] = useState(false);
  const [run, setRun] = useState<HumanRun | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const resume = useRef<{ runId: string; after: number } | null>(null);
  const activeConversation = useRef(conversationId);
  const refreshSequence = useRef(0);
  const decisions = useRef(
    new Map<string, { body: string; idempotencyKey: string }>()
  );
  const onEnabledChangeRef = useRef(onEnabledChange);
  activeConversation.current = conversationId;

  useEffect(() => {
    onEnabledChangeRef.current = onEnabledChange;
  }, [onEnabledChange]);

  useEffect(() => {
    let active = true;
    humanInteractionClient
      .capabilities()
      .then((value) => {
        if (!active) return;
        setAvailable(value.enabled);
        if (value.enabled && value.accept_new_runs !== false) {
          onEnabledChangeRef.current(true);
        }
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    const requestedConversation = conversationId;
    const sequence = ++refreshSequence.current;
    if (!conversationId) {
      setRun(null);
      return null;
    }
    try {
      const value = await humanInteractionClient.conversation(conversationId);
      if (
        activeConversation.current !== requestedConversation ||
        refreshSequence.current !== sequence
      ) {
        return null;
      }
      setRun(value);
      setError("");
      if (!value || !STREAM_RECONNECT_STATUSES.has(value.status)) {
        resume.current = null;
      }
      return value;
    } catch (cause) {
      if (
        activeConversation.current !== requestedConversation ||
        refreshSequence.current !== sequence
      ) {
        return null;
      }
      setError(cause instanceof Error ? cause.message : String(cause));
      return null;
    }
  }, [conversationId]);

  useEffect(() => {
    setRun(null);
    setError("");
    resume.current = null;
    decisions.current.clear();
    if (!available || !conversationId) return;

    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (!active) return;
      await refresh();
      if (active) timer = setTimeout(poll, 1500);
    };
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [available, conversationId, refresh]);

  useEffect(() => {
    if (isRunning || !resume.current) return;
    let active = true;
    void refresh().then((latestRun) => {
      if (!active || !resume.current) return;
      if (latestRun && STREAM_RECONNECT_STATUSES.has(latestRun.status)) {
        const pendingResume = resume.current;
        resume.current = null;
        onContinue(pendingResume.runId, pendingResume.after);
      } else {
        resume.current = null;
      }
    });
    return () => {
      active = false;
    };
  }, [isRunning, onContinue, refresh, run?.status]);

  const scopedRun = run?.conversation_id === conversationId ? run : null;
  const active = Boolean(scopedRun && ACTIVE_STATUSES.has(scopedRun.status));

  const control = useCallback(
    async (action: "pause" | "terminate") => {
      if (!run) return;
      setBusy(true);
      setError("");
      try {
        const nextRun = await humanInteractionClient.control(
          run.run_id,
          action
        );
        refreshSequence.current += 1;
        setRun(nextRun);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        setBusy(false);
      }
    },
    [run]
  );

  const reconnect = useCallback(() => {
    if (!run || isRunning) return;
    onContinue(run.run_id, 0);
  }, [isRunning, onContinue, run]);

  const decide = useCallback(
    async (
      item: HumanRequest,
      decision: HumanDecision,
      response: string | HumanClarificationAnswer[]
    ) => {
      const body = JSON.stringify([decision, response]);
      const previous = decisions.current.get(item.request_id);
      const idempotencyKey =
        previous?.body === body ? previous.idempotencyKey : crypto.randomUUID();
      decisions.current.set(item.request_id, { body, idempotencyKey });
      setBusy(true);
      setError("");
      try {
        await humanInteractionClient.decide(
          item,
          decision,
          response,
          idempotencyKey
        );
        refreshSequence.current += 1;
        const currentRun = run;
        if (currentRun) {
          resume.current = {
            runId: currentRun.run_id,
            after: currentRun.event_seq,
          };
          setRun({
            ...currentRun,
            status: "READY",
            requests: currentRun.requests.filter(
              (request) => request.request_id !== item.request_id
            ),
          });
        }
      } catch (cause) {
        const message = cause instanceof Error ? cause.message : String(cause);
        setError(message);
        throw cause;
      } finally {
        setBusy(false);
      }
    },
    [run]
  );

  return useMemo(
    () => ({
      available,
      run: scopedRun,
      active,
      pending: Boolean(scopedRun?.requests?.length),
      streaming: isRunning,
      error,
      busy,
      control,
      reconnect,
      decide,
      refresh,
    }),
    [
      active,
      available,
      busy,
      control,
      decide,
      error,
      isRunning,
      reconnect,
      refresh,
      scopedRun,
    ]
  );
}
