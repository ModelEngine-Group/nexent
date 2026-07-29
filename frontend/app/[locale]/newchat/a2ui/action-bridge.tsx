"use client";

import { useEffect } from "react";
import { useAui } from "@assistant-ui/react";
import {
  A2UI_ACTION_EVENT,
  failA2UIAction,
  isSameA2UISession,
  normalizeA2UIActionLabel,
} from "./runtime";

export function A2UIActionBridge({
  sessionKey,
  agentId,
  conversationId,
  enablePlan = false,
}: {
  sessionKey?: string;
  agentId?: string | number;
  conversationId?: string | number;
  enablePlan?: boolean;
}) {
  const aui = useAui();
  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (
        event as CustomEvent<{
          sessionKey?: string;
          submissionId?: string;
          actionLabel?: string;
        }>
      ).detail;
      if (!sessionKey || !detail?.sessionKey || !detail.submissionId) {
        return;
      }
      if (!isSameA2UISession(sessionKey, detail.sessionKey)) {
        return;
      }
      try {
        const result = aui.thread().append({
          role: "user",
          content: [
            {
              type: "text",
              text: normalizeA2UIActionLabel(detail.actionLabel),
            },
          ],
          runConfig: {
            custom: {
              a2uiSessionKey: detail.sessionKey,
              ...(agentId != null ? { agentId } : {}),
              ...(conversationId != null
                ? { threadId: String(conversationId) }
                : {}),
              enablePlan,
            },
          },
          startRun: true,
        });
        void Promise.resolve(result).catch((error: unknown) => {
          failA2UIAction(
            detail.submissionId,
            error instanceof Error ? error : new Error("A2UI action failed")
          );
        });
      } catch (error) {
        failA2UIAction(
          detail.submissionId,
          error instanceof Error ? error : new Error("A2UI action failed")
        );
      }
    };
    window.addEventListener(A2UI_ACTION_EVENT, handler);
    return () => window.removeEventListener(A2UI_ACTION_EVENT, handler);
  }, [agentId, aui, conversationId, enablePlan, sessionKey]);
  return null;
}
