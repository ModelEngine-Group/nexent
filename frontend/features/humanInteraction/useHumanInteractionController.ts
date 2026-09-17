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
  // Rate-limit snapshot requests to avoid thundering herds when the agent
  // stream emits many HITL chunks (thinking, parse, model_output_thinking…)
  // per second — the adapter's chunk loop and our SSE subscription each try
  // to refresh on every event, which would otherwise multiply into 10+
  // HTTP calls per second. Two guards protect us:
  //   1. `refreshInFlight` — dedupe concurrent callers; one snapshot in
  //      flight absorbs all requests that arrive before it resolves.
  //   2. `lastSnapshotAt` — minimum 3s between snapshots so even a burst
  //      after the in-flight resolves does not immediately re-hit the DB.
  const refreshInFlight = useRef(false);
  const lastSnapshotAt = useRef(0);
  const MIN_SNAPSHOT_INTERVAL_MS = 3000;
  // Mirror of the latest `run` state for use inside refresh guards. Using a
  // ref (instead of closing over `run`) keeps `refresh` stable so downstream
  // effects do not re-run on every snapshot.
  const runRef = useRef<HumanRun | null>(null);
  activeConversation.current = conversationId;

  // Tracks which run we currently have an SSE subscription open for.
  // When this changes, the subscription effect tears down the old one and opens a new one.
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
    // Guard 1: already a snapshot in flight — coalesce, don't duplicate.
    if (refreshInFlight.current) {
      return runRef.current;
    }
    // Guard 2: minimum interval since last snapshot — skip if too soon.
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

  // ──────────────────────────────────────────────────────────────────────────
  // Discovery: one-shot snapshots at conversation change and agent-pause.
  //
  // No polling anywhere in this file. We refresh exactly when we know a
  // fresh snapshot is needed:
  //   1. The user switched conversationId → a new HITL run might exist there.
  //   2. The agent stream just paused (isRunning went true → false) → the
  //      most likely moment a HITL run was just created (ask_user()).
  //
  // After a snapshot reveals a run, the SSE subscription below takes over
  // and keeps the run state live without further HTTP polling.
  // ──────────────────────────────────────────────────────────────────────────

  useEffect(() => {
    // conversationId changed: clear stale state and snapshot once.
    runRef.current = null;
    setRun(null);
    setError("");
    resume.current = null;
    decisions.current.clear();
    setActiveRunId(null);
    if (!available || !conversationId) return;
    void refresh();
    // Intentionally does NOT depend on refresh — we want a one-shot fire
    // when conversationId changes, not a re-snapshot every time refresh is
    // recreated (e.g. when auth headers drift).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [available, conversationId]);

  useEffect(() => {
    // Agent stream just paused → a HITL run may have been created mid-turn.
    // Snapshot once to discover it; SSE will then keep us updated. The dual
    // guards inside refresh() (in-flight dedupe + 3s min interval) already
    // handle any burst from isRunning thrashing or adapter callbacks.
    if (isRunning || !available || !conversationId) return;
    void refresh();
  }, [isRunning, available, conversationId, refresh]);

  // Incremented to force SSE resubscribe after a transient network disconnect.
  // Terminal-status closes from the backend do NOT bump this — we don't want
  // to reconnect runs that are already COMPLETED/FAILED.
  const [retryTick, setRetryTick] = useState(0);

  // ──────────────────────────────────────────────────────────────────────────
  // SSE subscription to the HITL run events stream.
  //
  // Once the discovery effects below set activeRunId, this effect opens an
  // EventSource against GET /{run_id}/events. The native EventSource API has
  // built-in auto-reconnect with exponential backoff, so transient network
  // drops heal themselves. We only proactively close on terminal status.
  //
  // Every non-heartbeat event triggers a single refresh() — event-driven
  // (1 HTTP call per SSE event) vs the original timer-driven polling
  // (12+ calls/min regardless of activity).
  // ──────────────────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!activeRunId) return;

    let tornDown = false;
    let stoppedByUs = false;
    const url = `${API_BASE_URL}/agent/human-interactions/${activeRunId}/events?after_event=${run?.event_seq ?? 0}`;
    const es = new EventSource(url);

    es.onmessage = (ev) => {
      if (tornDown || stoppedByUs) return;
      if (!ev.data) return;
      // Detect terminal status inside a human_run event so we can close the
      // stream proactively and stop EventSource from auto-reconnecting
      // forever against a run that is already COMPLETED/FAILED.
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
          // One final refresh so the UI has the definitive terminal snapshot.
          void refresh();
          return;
        }
      } catch {
        // Not JSON — still refresh, just don't try to parse.
      }
      void refresh();
    };

    es.onerror = () => {
      if (tornDown || stoppedByUs) return;
      // Leave the native EventSource auto-reconnect behaviour alone — it
      // already handles transient drops with exponential backoff. When the
      // browser gives up entirely (after many retries), we do one snapshot
      // and retry from scratch after 2s if the run is still alive.
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

  // ──────────────────────────────────────────────────────────────────────────
  // Drive activeRunId from run snapshot.
  //
  // When refresh() returns a non-null run we subscribe to its events stream.
  // When it returns null we tear down any existing subscription.
  // ──────────────────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!run) {
      setActiveRunId((prev) => (prev ? null : prev));
      return;
    }
    setActiveRunId((prev) => (prev !== run.run_id ? run.run_id : prev));
  }, [run]);

  // ──────────────────────────────────────────────────────────────────────────
  // Agent stream resume (unchanged from original logic).
  // ──────────────────────────────────────────────────────────────────────────

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
