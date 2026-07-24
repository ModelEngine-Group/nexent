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

import type { Nl2AgentActionContext } from "@/lib/chat/nl2agentContinuation";
import {
  getNl2AgentSessionState,
  resumeNl2AgentSession,
  type Nl2AgentSessionState,
  type Nl2AgentSessionSummary,
} from "@/services/nl2agentService";

export interface Nl2AgentContinuationRequest {
  kind: "action";
  context: Nl2AgentActionContext;
}

interface Nl2AgentWorkflowContextValue {
  active: boolean;
  editable: boolean;
  agentId?: number;
  continueWithAction: (context: Nl2AgentActionContext) => Promise<void>;
  beginAction: () => void;
  endAction: () => void;
  setInputBlocked: (key: string, blocked: boolean) => void;
  notifyStateChanged: () => void;
  busy: boolean;
  stateVersion: number;
  sessionState?: Nl2AgentSessionState;
  sessionStateLoading: boolean;
  sessionStateError?: string;
  latestWorkflowRevision?: number;
  getLatestWorkflowRevision: () => number | undefined;
  updateWorkflowRevision: (revision: number) => void;
  refreshSessionState: () => Promise<void>;
  resumeSession: () => Promise<void>;
  resuming: boolean;
}

const Nl2AgentWorkflowContext = createContext<Nl2AgentWorkflowContextValue>({
  active: false,
  editable: false,
  continueWithAction: async () => {},
  beginAction: () => {},
  endAction: () => {},
  setInputBlocked: () => {},
  notifyStateChanged: () => {},
  busy: false,
  stateVersion: 0,
  sessionStateLoading: false,
  getLatestWorkflowRevision: () => undefined,
  updateWorkflowRevision: () => {},
  refreshSessionState: async () => {},
  resumeSession: async () => {},
  resuming: false,
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
  const scopedAgentId = useMemo(() => {
    if (agentId) return agentId;
    const match = scopeKey.match(/(?:^|:)draft:(\d+)(?:$|:)/);
    const parsed = Number(match?.[1]);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
  }, [agentId, scopeKey]);
  const [actionCount, setActionCount] = useState(0);
  const [continuing, setContinuing] = useState(false);
  const [inputBlockers, setInputBlockers] = useState<Set<string>>(new Set());
  const [stateVersion, setStateVersion] = useState(0);
  const [sessionState, setSessionState] = useState<Nl2AgentSessionState>();
  const [sessionStateLoading, setSessionStateLoading] = useState(false);
  const [sessionStateError, setSessionStateError] = useState<string>();
  const [latestWorkflowRevision, setLatestWorkflowRevision] =
    useState<number>();
  const [resuming, setResuming] = useState(false);
  const continuingRef = useRef(false);
  const sessionRequestRef = useRef(0);
  const workflowRevisionRef = useRef<{
    agentId?: number;
    revision?: number;
  }>({});
  const onContinueRef = useRef(onContinue);
  const onStateChangedRef = useRef(onStateChanged);

  onContinueRef.current = onContinue;
  onStateChangedRef.current = onStateChanged;

  const updateWorkflowRevision = useCallback(
    (revision: number) => {
      if (!Number.isInteger(revision) || revision < 0 || !scopedAgentId) return;
      const current =
        workflowRevisionRef.current.agentId === scopedAgentId
          ? workflowRevisionRef.current.revision
          : undefined;
      const nextRevision = Math.max(current ?? 0, revision);
      workflowRevisionRef.current = {
        agentId: scopedAgentId,
        revision: nextRevision,
      };
      setLatestWorkflowRevision(nextRevision);
    },
    [scopedAgentId]
  );
  const getLatestWorkflowRevision = useCallback(
    () =>
      workflowRevisionRef.current.agentId === scopedAgentId
        ? workflowRevisionRef.current.revision
        : undefined,
    [scopedAgentId]
  );

  useEffect(() => {
    setInputBlockers(new Set());
  }, [scopeKey]);

  const refreshSessionState = useCallback(async () => {
    if (!enabled || !scopedAgentId) return;
    const requestId = ++sessionRequestRef.current;
    setSessionStateLoading(true);
    setSessionStateError(undefined);
    try {
      const nextState = await getNl2AgentSessionState(scopedAgentId);
      if (sessionRequestRef.current === requestId) {
        updateWorkflowRevision(nextState.revision);
        setSessionState(nextState);
      }
    } catch (error) {
      if (sessionRequestRef.current !== requestId) return;
      setSessionStateError(
        error instanceof Error
          ? error.message
          : "Unable to load NL2AGENT session state."
      );
    } finally {
      if (sessionRequestRef.current === requestId) {
        setSessionStateLoading(false);
      }
    }
  }, [enabled, scopedAgentId, updateWorkflowRevision]);

  useEffect(() => {
    if (!enabled || !scopedAgentId) {
      sessionRequestRef.current += 1;
      setSessionState(undefined);
      workflowRevisionRef.current = {};
      setLatestWorkflowRevision(undefined);
      setSessionStateError(undefined);
      setSessionStateLoading(false);
      return;
    }
    setSessionState(undefined);
    workflowRevisionRef.current = {};
    setLatestWorkflowRevision(undefined);
  }, [enabled, scopeKey, scopedAgentId]);

  useEffect(() => {
    if (!enabled || !scopedAgentId) return;
    void refreshSessionState();
    return () => {
      sessionRequestRef.current += 1;
    };
  }, [enabled, refreshSessionState, scopeKey, scopedAgentId, stateVersion]);

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
    if (!enabled || !scopedAgentId || resuming) return;
    setResuming(true);
    try {
      const session = await resumeNl2AgentSession(scopedAgentId);
      onSessionResumed?.(session);
      setStateVersion((version) => version + 1);
    } finally {
      setResuming(false);
    }
  }, [enabled, onSessionResumed, resuming, scopedAgentId]);
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
    async (request: Nl2AgentContinuationRequest) => {
      if (!editable || continuingRef.current) return;
      continuingRef.current = true;
      setContinuing(true);
      try {
        await onContinueRef.current(request);
      } finally {
        continuingRef.current = false;
        setContinuing(false);
      }
    },
    [editable]
  );

  const continueWithAction = useCallback(
    async (context: Nl2AgentActionContext) => {
      await continueRequest({ kind: "action", context });
    },
    [continueRequest]
  );

  const value = useMemo<Nl2AgentWorkflowContextValue>(
    () => ({
      active: enabled && editable,
      editable,
      agentId: scopedAgentId,
      continueWithAction,
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
      latestWorkflowRevision,
      getLatestWorkflowRevision,
      updateWorkflowRevision,
      refreshSessionState,
      resumeSession,
      resuming,
    }),
    [
      actionCount,
      beginAction,
      continueWithAction,
      continuing,
      editable,
      enabled,
      endAction,
      inputBlockers,
      getLatestWorkflowRevision,
      latestWorkflowRevision,
      notifyStateChanged,
      refreshSessionState,
      resumeSession,
      resuming,
      scopedAgentId,
      sessionState,
      sessionStateError,
      sessionStateLoading,
      setInputBlocked,
      stateVersion,
      updateWorkflowRevision,
    ]
  );

  return (
    <Nl2AgentWorkflowContext.Provider value={value}>
      {children}
    </Nl2AgentWorkflowContext.Provider>
  );
};

export const useNl2AgentWorkflow = () => useContext(Nl2AgentWorkflowContext);
