"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { NL2AGENT_AUTO_CONTINUE_PREFIX } from "@/lib/chat/nl2agentContinuation";
import type { Nl2AgentUserAction } from "@/lib/chat/nl2agentContinuation";
import {
  getNl2AgentSessionState,
  resumeNl2AgentSession,
  type Nl2AgentSessionSummary,
  type Nl2AgentSessionState,
} from "@/services/nl2agentService";

export { NL2AGENT_AUTO_CONTINUE_PREFIX };

export type Nl2AgentContinuationRequest =
  | { kind: "automatic"; text: string }
  | { kind: "user_action"; text: string; action: Nl2AgentUserAction };

interface Nl2AgentWorkflowContextValue {
  active: boolean;
  editable: boolean;
  agentId?: number;
  continueWithText: (text?: string) => Promise<void>;
  continueWithUserAction: (
    text: string | undefined,
    action: Nl2AgentUserAction
  ) => Promise<void>;
  beginAction: () => void;
  endAction: () => void;
  setInputBlocked: (key: string, blocked: boolean) => void;
  notifyStateChanged: () => void;
  busy: boolean;
  stateVersion: number;
  sessionState?: Nl2AgentSessionState;
  sessionStateLoading: boolean;
  sessionStateError?: string;
  refreshSessionState: () => Promise<void>;
  resumeSession: () => Promise<void>;
  resuming: boolean;
  continuationError?: string;
  retryContinuation: () => Promise<void>;
  claimCardDelivery: (key: string) => boolean;
  completeCardDelivery: (key: string) => void;
  failCardDelivery: (key: string) => void;
}

const Nl2AgentWorkflowContext = createContext<Nl2AgentWorkflowContextValue>({
  active: false,
  editable: false,
  continueWithText: async () => {},
  continueWithUserAction: async () => {},
  beginAction: () => {},
  endAction: () => {},
  setInputBlocked: () => {},
  notifyStateChanged: () => {},
  busy: false,
  stateVersion: 0,
  sessionStateLoading: false,
  refreshSessionState: async () => {},
  resumeSession: async () => {},
  resuming: false,
  retryContinuation: async () => {},
  claimCardDelivery: () => false,
  completeCardDelivery: () => {},
  failCardDelivery: () => {},
});

export const Nl2AgentWorkflowProvider: React.FC<{
  children: React.ReactNode;
  onContinue: (request: Nl2AgentContinuationRequest) => Promise<void>;
  enabled: boolean;
  editable?: boolean;
  scopeKey: string;
  agentId?: number | null;
  onSessionResumed?: (session: Nl2AgentSessionSummary) => void;
  onStateChanged?: () => void;
}> = ({
  children,
  onContinue,
  enabled,
  editable = enabled,
  scopeKey,
  agentId,
  onSessionResumed,
  onStateChanged,
}) => {
  const [actionCount, setActionCount] = useState(0);
  const [continuing, setContinuing] = useState(false);
  const [inputBlockers, setInputBlockers] = useState<Set<string>>(new Set());
  const [stateVersion, setStateVersion] = useState(0);
  const [sessionState, setSessionState] = useState<Nl2AgentSessionState>();
  const [sessionStateLoading, setSessionStateLoading] = useState(false);
  const [sessionStateError, setSessionStateError] = useState<string>();
  const [resuming, setResuming] = useState(false);
  const [retries, setRetries] = useState<
    Record<string, { request: Nl2AgentContinuationRequest; error: string }>
  >({});
  const continuingRef = useRef(false);
  const sessionRequestRef = useRef(0);
  const onContinueRef = useRef(onContinue);
  const onStateChangedRef = useRef(onStateChanged);
  const cardDeliveriesRef = useRef<
    Map<string, "pending" | "succeeded" | "failed">
  >(new Map());

  onContinueRef.current = onContinue;
  onStateChangedRef.current = onStateChanged;

  useEffect(() => {
    setInputBlockers(new Set());
    cardDeliveriesRef.current.clear();
  }, [scopeKey]);

  const refreshSessionState = useCallback(async () => {
    if (!enabled || !agentId) return;
    const requestId = ++sessionRequestRef.current;
    setSessionStateLoading(true);
    setSessionStateError(undefined);
    try {
      const nextState = await getNl2AgentSessionState(agentId);
      if (sessionRequestRef.current === requestId) setSessionState(nextState);
    } catch (error) {
      if (sessionRequestRef.current !== requestId) return;
      setSessionStateError(
        error instanceof Error
          ? error.message
          : "Unable to load NL2AGENT session state."
      );
    } finally {
      if (sessionRequestRef.current === requestId)
        setSessionStateLoading(false);
    }
  }, [agentId, enabled]);

  useEffect(() => {
    if (!enabled || !agentId) {
      sessionRequestRef.current += 1;
      setSessionState(undefined);
      setSessionStateError(undefined);
      setSessionStateLoading(false);
      return;
    }
    setSessionState(undefined);
  }, [agentId, enabled, scopeKey]);

  useEffect(() => {
    if (!enabled || !agentId) return;
    void refreshSessionState();
    return () => {
      sessionRequestRef.current += 1;
    };
  }, [agentId, enabled, refreshSessionState, scopeKey, stateVersion]);

  const claimCardDelivery = useCallback((key: string) => {
    const status = cardDeliveriesRef.current.get(key);
    if (status === "pending" || status === "succeeded") return false;
    cardDeliveriesRef.current.set(key, "pending");
    return true;
  }, []);
  const completeCardDelivery = useCallback((key: string) => {
    cardDeliveriesRef.current.set(key, "succeeded");
  }, []);
  const failCardDelivery = useCallback((key: string) => {
    cardDeliveriesRef.current.set(key, "failed");
  }, []);

  const beginAction = useCallback(
    () => setActionCount((count) => count + 1),
    []
  );
  const endAction = useCallback(
    () => setActionCount((count) => Math.max(0, count - 1)),
    []
  );
  const notifyStateChanged = useCallback(() => {
    setStateVersion((version) => version + 1);
    onStateChangedRef.current?.();
  }, []);
  const resumeSession = useCallback(async () => {
    if (!enabled || !agentId || resuming) return;
    setResuming(true);
    try {
      const session = await resumeNl2AgentSession(agentId);
      onSessionResumed?.(session);
      setStateVersion((version) => version + 1);
    } finally {
      setResuming(false);
    }
  }, [agentId, enabled, onSessionResumed, resuming]);
  const setInputBlocked = useCallback((key: string, blocked: boolean) => {
    setInputBlockers((current) => {
      if (current.has(key) === blocked) return current;
      const next = new Set(current);
      if (blocked) next.add(key);
      else next.delete(key);
      return next;
    });
  }, []);

  const continueRequest = useCallback(
    async (request?: Nl2AgentContinuationRequest) => {
      if (!editable || !request?.text || continuingRef.current) return;
      continuingRef.current = true;
      setContinuing(true);
      setRetries((current) => {
        const next = { ...current };
        delete next[scopeKey];
        return next;
      });
      try {
        await onContinueRef.current(request);
      } catch (error) {
        setRetries((current) => ({
          ...current,
          [scopeKey]: {
            request,
            error:
              error instanceof Error
                ? error.message
                : "Unable to continue NL2AGENT.",
          },
        }));
      } finally {
        continuingRef.current = false;
        setContinuing(false);
      }
    },
    [editable, scopeKey]
  );

  const continueWithText = useCallback(
    async (text?: string) => {
      if (text) await continueRequest({ kind: "automatic", text });
    },
    [continueRequest]
  );

  const continueWithUserAction = useCallback(
    async (text: string | undefined, action: Nl2AgentUserAction) => {
      if (text) await continueRequest({ kind: "user_action", text, action });
    },
    [continueRequest]
  );

  const retryContinuation = useCallback(async () => {
    const retry = retries[scopeKey];
    if (retry) await continueRequest(retry.request);
  }, [continueRequest, retries, scopeKey]);

  const continuationError = retries[scopeKey]?.error;

  const value = useMemo<Nl2AgentWorkflowContextValue>(
    () => ({
      active: enabled && editable,
      editable,
      agentId: agentId ?? undefined,
      continueWithText,
      continueWithUserAction,
      beginAction,
      endAction,
      setInputBlocked,
      notifyStateChanged,
      busy:
        continuing ||
        actionCount > 0 ||
        inputBlockers.size > 0 ||
        (enabled && !editable),
      stateVersion,
      sessionState,
      sessionStateLoading,
      sessionStateError,
      refreshSessionState,
      resumeSession,
      resuming,
      continuationError,
      retryContinuation,
      claimCardDelivery,
      completeCardDelivery,
      failCardDelivery,
    }),
    [
      actionCount,
      agentId,
      beginAction,
      continueWithText,
      continueWithUserAction,
      continuationError,
      continuing,
      endAction,
      enabled,
      editable,
      inputBlockers,
      notifyStateChanged,
      refreshSessionState,
      resumeSession,
      resuming,
      retryContinuation,
      claimCardDelivery,
      completeCardDelivery,
      failCardDelivery,
      setInputBlocked,
      sessionState,
      sessionStateError,
      sessionStateLoading,
      stateVersion,
    ]
  );

  return (
    <Nl2AgentWorkflowContext.Provider value={value}>
      {children}
    </Nl2AgentWorkflowContext.Provider>
  );
};

export const useNl2AgentWorkflow = () => useContext(Nl2AgentWorkflowContext);
