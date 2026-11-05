// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  createContext,
  useContext,
  useMemo,
  type FC,
  type ReactNode,
} from "react";

/**
 * Conversation-wide artifacts state exposed to assistant messages.
 *
 * The thread root aggregates every agent-generated file and owns the side
 * panel's open state, while the "view all artifacts" entry is rendered at the
 * end of each assistant message. This context bridges the two without prop
 * drilling through the assistant-ui message renderers.
 */
export interface ConversationArtifactsEntryValue {
  /** Total agent-generated files collected across the conversation. */
  count: number;
  /** Opens the conversation artifacts panel. */
  open: () => void;
}

const ConversationArtifactsEntryContext = createContext<
  ConversationArtifactsEntryValue | null
>(null);

export interface ConversationArtifactsEntryProviderProps
  extends ConversationArtifactsEntryValue {
  children: ReactNode;
}

export const ConversationArtifactsEntryProvider: FC<
  ConversationArtifactsEntryProviderProps
> = ({ count, open, children }) => {
  // The thread root re-renders on every streamed token; a memoized value
  // keeps message-level consumers from re-rendering unless the count changed.
  const value = useMemo(() => ({ count, open }), [count, open]);
  return (
    <ConversationArtifactsEntryContext.Provider value={value}>
      {children}
    </ConversationArtifactsEntryContext.Provider>
  );
};

/**
 * Returns the conversation artifacts entry state, or null when no provider
 * is mounted (e.g. message surfaces outside the main thread).
 */
export function useConversationArtifactsEntry() {
  return useContext(ConversationArtifactsEntryContext);
}
