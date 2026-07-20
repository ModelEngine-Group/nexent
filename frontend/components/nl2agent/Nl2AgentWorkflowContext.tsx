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
import {
  getNl2AgentSessionState,
  type Nl2AgentSessionState,
} from "@/services/nl2agentService";

export { NL2AGENT_AUTO_CONTINUE_PREFIX };

interface Nl2AgentWorkflowContextValue {
  active: boolean;
  continueWithText: (text?: string) => Promise<void>;
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
  continuationError?: string;
  retryContinuation: () => Promise<void>;
  claimCardDelivery: (key: string) => boolean;
  completeCardDelivery: (key: string) => void;
  failCardDelivery: (key: string) => void;
}

const Nl2AgentWorkflowContext = createContext<Nl2AgentWorkflowContextValue>({
  active: false,
  continueWithText: async () => {},
  beginAction: () => {},
  endAction: () => {},
  setInputBlocked: () => {},
  notifyStateChanged: () => {},
  busy: false,
  stateVersion: 0,
  sessionStateLoading: false,
  refreshSessionState: async () => {},
  retryContinuation: async () => {},
  claimCardDelivery: () => false,
  completeCardDelivery: () => {},
  failCardDelivery: () => {},
});

export const Nl2AgentWorkflowProvider: React.FC<{
  children: React.ReactNode;
  onContinue: (text: string) => Promise<void>;
  enabled: boolean;
  scopeKey: string;
  agentId?: number | null;
}> = ({ children, onContinue, enabled, scopeKey, agentId }) => {
  const [actionCount, setActionCount] = useState(0);
  const [continuing, setContinuing] = useState(false);
  const [inputBlockers, setInputBlockers] = useState<Set<string>>(new Set());
  const [stateVersion, setStateVersion] = useState(0);
  const [sessionState, setSessionState] = useState<Nl2AgentSessionState>();
  const [sessionStateLoading, setSessionStateLoading] = useState(false);
  const [sessionStateError, setSessionStateError] = useState<string>();
  const [retries, setRetries] = useState<
    Record<string, { text: string; error: string }>
  >({});
  const continuingRef = useRef(false);
  const sessionRequestRef = useRef(0);
  const cardDeliveriesRef = useRef<
    Map<string, "pending" | "succeeded" | "failed">
  >(new Map());

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
  const notifyStateChanged = useCallback(
    () => setStateVersion((version) => version + 1),
    []
  );
  const setInputBlocked = useCallback((key: string, blocked: boolean) => {
    setInputBlockers((current) => {
      const next = new Set(current);
      if (blocked) next.add(key);
      else next.delete(key);
      return next;
    });
  }, []);

  const continueWithText = useCallback(
    async (text?: string) => {
      if (!enabled || !text || continuingRef.current) return;
      continuingRef.current = true;
      setContinuing(true);
      setRetries((current) => {
        const next = { ...current };
        delete next[scopeKey];
        return next;
      });
      try {
        await onContinue(text);
      } catch (error) {
        setRetries((current) => ({
          ...current,
          [scopeKey]: {
            text,
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
    [enabled, onContinue, scopeKey]
  );

  const retryContinuation = useCallback(async () => {
    const retry = retries[scopeKey];
    if (retry) await continueWithText(retry.text);
  }, [continueWithText, retries, scopeKey]);

  const continuationError = retries[scopeKey]?.error;

  const value = useMemo<Nl2AgentWorkflowContextValue>(
    () => ({
      active: enabled,
      continueWithText,
      beginAction,
      endAction,
      setInputBlocked,
      notifyStateChanged,
      busy: continuing || actionCount > 0 || inputBlockers.size > 0,
      stateVersion,
      sessionState,
      sessionStateLoading,
      sessionStateError,
      refreshSessionState,
      continuationError,
      retryContinuation,
      claimCardDelivery,
      completeCardDelivery,
      failCardDelivery,
    }),
    [
      actionCount,
      beginAction,
      continueWithText,
      continuationError,
      continuing,
      endAction,
      enabled,
      inputBlockers,
      notifyStateChanged,
      refreshSessionState,
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
