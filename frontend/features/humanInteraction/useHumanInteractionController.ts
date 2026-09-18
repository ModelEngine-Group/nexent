"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { API_BASE_URL } from "@/services/api";
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
const TERMINAL_STATUSES = new Set([
  "COMPLETED",
  "FAILED",
  "STOPPED",
  "EXPIRED",
  "RECOVERY_REQUIRED",
]);

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
  // Rate-limit snapshots: dedupe in-flight callers and enforce a 3s min interval.
  const refreshInFlight = useRef(false);
  const lastSnapshotAt = useRef(0);
  const MIN_SNAPSHOT_INTERVAL_MS = 3000;
  // Mirror of the latest `run` state; keeps `refresh` dependencies stable.
  const runRef = useRef<HumanRun | null>(null);
  activeConversation.current = conversationId;

  const [activeRunId, setActiveRunId] = useState<string | null>(null);

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
    if (!conversationId) {
      runRef.current = null;
      setRun(null);
      setActiveRunId(null);
      return null;
    }
    // Guard 1: coalesce while a snapshot is in flight.
    if (refreshInFlight.current) {
      return runRef.current;
    }
    // Guard 2: respect the minimum snapshot interval.
    const now = Date.now();
    if (now - lastSnapshotAt.current < MIN_SNAPSHOT_INTERVAL_MS) {
      return runRef.current;
    }
    refreshInFlight.current = true;
    lastSnapshotAt.current = now;
    const sequence = ++refreshSequence.current;
    try {
      const value = await humanInteractionClient.conversation(conversationId);
      if (
        activeConversation.current !== requestedConversation ||
        refreshSequence.current !== sequence
      ) {
        return null;
      }
      runRef.current = value;
      setRun(value);
      setError("");
      if (value) {
        if (!STREAM_RECONNECT_STATUSES.has(value.status)) {
          resume.current = null;
        }
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
    } finally {
      refreshInFlight.current = false;
    }
  }, [conversationId]);

  /**
   * Discovery: one-shot snapshots at conversation change and agent pause.
   * After a snapshot reveals a run, the SSE subscription below keeps it live.
   */

  useEffect(() => {
    runRef.current = null;
    setRun(null);
    setError("");
    resume.current = null;
    decisions.current.clear();
    setActiveRunId(null);
    if (!available || !conversationId) return;
    void refresh();
    // One-shot fire on conversation change; do not re-run when refresh changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [available, conversationId]);

  useEffect(() => {
    // Agent stream paused → a HITL run may have just been created (ask_user).
    if (isRunning || !available || !conversationId) return;
    void refresh();
  }, [isRunning, available, conversationId, refresh]);

  // Retry tick for SSE resubscribe after transient network disconnects;
  // terminal closes must not trigger a reconnect.
  const [retryTick, setRetryTick] = useState(0);

  /**
   * SSE subscription to the run events stream; every event triggers one
   * rate-limited refresh(). Native auto-reconnect handles transient drops.
   */

  useEffect(() => {
    if (!activeRunId) return;

    let tornDown = false;
    let stoppedByUs = false;
    const url = `${API_BASE_URL}/agent/human-interactions/${activeRunId}/events?after_event=${run?.event_seq ?? 0}`;
    const es = new EventSource(url);

    es.onmessage = (ev) => {
      if (tornDown || stoppedByUs) return;
      if (!ev.data) return;
      // Close proactively on terminal status so EventSource stops
      // auto-reconnecting against a run that already finished.
      try {
        const parsed = JSON.parse(ev.data);
        if (
          parsed.type === "human_run" &&
          parsed.content &&
          typeof parsed.content === "object" &&
          TERMINAL_STATUSES.has(parsed.content.status)
        ) {
          stoppedByUs = true;
          es.close();
          void refresh();
          return;
        }
      } catch {
        // Not JSON — refresh without parsing.
      }
      void refresh();
    };

    es.onerror = () => {
      if (tornDown || stoppedByUs) return;
      // Let native auto-reconnect handle transient drops; fall back to a
      // manual resubscribe once the browser gives up and the run is alive.
      void refresh().then((latest) => {
        if (tornDown || stoppedByUs) return;
        if (!latest || TERMINAL_STATUSES.has(latest.status)) return;
        es.close();
        stoppedByUs = true;
        setTimeout(() => {
          if (!tornDown) setRetryTick((c) => c + 1);
        }, 2000);
      });
    };

    return () => {
      tornDown = true;
      stoppedByUs = true;
      es.close();
    };
  }, [activeRunId, retryTick]);

  // Subscribe to a discovered run's events stream; null tears it down.

  useEffect(() => {
    if (!run) {
      setActiveRunId((prev) => (prev ? null : prev));
      return;
    }
    setActiveRunId((prev) => (prev !== run.run_id ? run.run_id : prev));
  }, [run]);

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
        runRef.current = nextRun;
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
          const nextRun = {
            ...currentRun,
            status: "READY" as const,
            requests: currentRun.requests.filter(
              (request) => request.request_id !== item.request_id
            ),
          };
          runRef.current = nextRun;
          setRun(nextRun);
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
