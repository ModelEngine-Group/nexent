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
  continuationError?: string;
  retryContinuation: () => Promise<void>;
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
  retryContinuation: async () => {},
});

export const Nl2AgentWorkflowProvider: React.FC<{
  children: React.ReactNode;
  onContinue: (text: string) => Promise<void>;
  enabled: boolean;
  scopeKey: string;
}> = ({ children, onContinue, enabled, scopeKey }) => {
  const [actionCount, setActionCount] = useState(0);
  const [continuing, setContinuing] = useState(false);
  const [inputBlockers, setInputBlockers] = useState<Set<string>>(new Set());
  const [stateVersion, setStateVersion] = useState(0);
  const [retries, setRetries] = useState<
    Record<string, { text: string; error: string }>
  >({});
  const continuingRef = useRef(false);

  useEffect(() => {
    setInputBlockers(new Set());
  }, [scopeKey]);

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
      continuationError,
      retryContinuation,
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
      retryContinuation,
      setInputBlocked,
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
