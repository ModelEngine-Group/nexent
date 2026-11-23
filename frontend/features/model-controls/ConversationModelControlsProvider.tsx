// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { ReasoningEffort } from "@/types/modelConfig";
import type { ModelParameterValue } from "@/types/modelParameterSettings";

export interface ModelState {
  enabled: boolean;
  effort: ReasoningEffort;
  budget: number;
}

interface SessionState {
  modelId: string;
  values: Record<string, ModelState>;
}

function useLocalModelControlsState() {
  const [sessions, setSessions] = useState<Record<string, SessionState>>({});
  const [sampling, setSampling] = useState<Record<string, ModelParameterValue>>(
    {}
  );
  const [rejected, setRejected] = useState<Record<string, boolean>>({});
  const [threadBindings, setThreadBindings] = useState<Record<string, string>>(
    {}
  );
  const bindThread = useCallback((threadId: string, serverId: string) => {
    const numericId = Number(serverId);
    if (!threadId || !Number.isSafeInteger(numericId) || numericId <= 0) return;
    const remoteId = String(numericId);
    setThreadBindings((current) =>
      current[remoteId] !== undefined
        ? current
        : { ...current, [remoteId]: threadId }
    );
  }, []);
  return useMemo(
    () => ({
      sessions,
      setSessions,
      sampling,
      setSampling,
      rejected,
      setRejected,
      threadBindings,
      bindThread,
    }),
    [sessions, sampling, rejected, threadBindings, bindThread]
  );
}

const ModelControlsContext = createContext<ReturnType<
  typeof useLocalModelControlsState
> | null>(null);

/** Owns controls for one chat page lifetime, above loading and landing views. */
export function ConversationModelControlsProvider({
  children,
}: {
  children: ReactNode;
}) {
  const state = useLocalModelControlsState();
  return (
    <ModelControlsContext.Provider value={state}>
      {children}
    </ModelControlsContext.Provider>
  );
}

export function useModelControlsState() {
  const shared = useContext(ModelControlsContext);
  const local = useLocalModelControlsState();
  return shared ?? local;
}

/** Keep a draft and its later server-backed history on the original cache key. */
export function useConversationModelThreadKey(
  threadId: string | undefined,
  remoteId?: string
) {
  const shared = useContext(ModelControlsContext);
  const localId = threadId ?? "new";
  if (!shared) return localId;
  const identity = remoteId || localId;
  return shared.threadBindings[identity] ?? identity;
}

export function useBindConversationModelThread() {
  return useContext(ModelControlsContext)?.bindThread;
}
