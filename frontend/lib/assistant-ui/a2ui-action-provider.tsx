"use client";

import { useEffect } from "react";
import { useAgUiSendA2uiAction } from "@assistant-ui/react-ag-ui";
import { _setSendA2uiAction } from "./a2ui-toolkit";

/**
 * Binds the `useAgUiSendA2uiAction` hook into the module-level bridge ref
 * that the A2UI action registry reads.  Must be mounted *inside* the
 * AssistantRuntimeProvider so `useAui()` resolves correctly.
 *
 * Mount this once near the top of the assistant UI tree.
 */
export function A2uiActionProvider({ children }: { children: React.ReactNode }) {
  const sendA2uiAction = useAgUiSendA2uiAction();

  useEffect(() => {
    _setSendA2uiAction(sendA2uiAction);
    return () => {
      _setSendA2uiAction(null);
    };
  }, [sendA2uiAction]);

  return <>{children}</>;
}
