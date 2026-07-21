"use client";

import { createContext, useContext, type FC, type ReactNode } from "react";
import type { PanelSourceItem } from "./sources-panel";

/**
 * State describing which source group is currently driving the panel.
 *
 * - `null` means no panel is mounted and any click should open a fresh one.
 * - Otherwise the panel belongs to a specific `(messageId, groupId)` pair and
 *   a tab; toggling the same pair closes the panel, opening a different pair
 *   replaces it.
 *
 * Carrying the raw source/image arrays in context (instead of recomputing them
 * from the assistant-ui store) avoids another selector subscription that
 * would otherwise re-render every `group-source` instance on each token.
 */
export interface SourcesPanelSelection {
  messageId: string;
  groupId: string;
  sources: PanelSourceItem[];
  images: PanelSourceItem[];
  selectedCiteIndex?: number;
}

export interface SourcesPanelContextValue {
  selection: SourcesPanelSelection | null;
  isOpen: boolean;
  open: (payload: SourcesPanelSelection) => void;
  toggle: (payload: SourcesPanelSelection) => void;
  close: () => void;
}

const SourcesPanelContext = createContext<SourcesPanelContextValue | null>(null);

export interface SourcesPanelProviderProps {
  value: SourcesPanelContextValue;
  children: ReactNode;
}

export const SourcesPanelProvider: FC<SourcesPanelProviderProps> = ({
  value,
  children,
}) => (
  <SourcesPanelContext.Provider value={value}>
    {children}
  </SourcesPanelContext.Provider>
);

/**
 * Hook used by child components (currently the `group-source` block) to read
 * and mutate the panel state owned by the surrounding `Thread` component.
 */
export const useSourcesPanel = (): SourcesPanelContextValue => {
  const ctx = useContext(SourcesPanelContext);
  if (!ctx) {
    throw new Error(
      "useSourcesPanel must be used inside <SourcesPanelProvider>.",
    );
  }
  return ctx;
};
