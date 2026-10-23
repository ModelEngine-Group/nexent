// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  createContext,
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
  return useMemo(
    () => ({
      sessions,
      setSessions,
      sampling,
      setSampling,
      rejected,
      setRejected,
    }),
    [sessions, sampling, rejected]
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
