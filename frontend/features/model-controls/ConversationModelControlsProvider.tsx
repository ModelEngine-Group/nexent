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
function useThreadBindings() {
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
      threadBindings,
      bindThread,
    }),
    [threadBindings, bindThread]
  );
}

const ModelControlsContext = createContext<ReturnType<
  typeof useThreadBindings
> | null>(null);

/** Owns controls for one chat page lifetime, above loading and landing views. */
export function ConversationModelControlsProvider({
  children,
}: {
  children: ReactNode;
}) {
  const state = useThreadBindings();
  return (
    <ModelControlsContext.Provider value={state}>
      {children}
    </ModelControlsContext.Provider>
  );
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
