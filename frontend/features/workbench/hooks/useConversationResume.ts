"use client";

import { useEffect, useRef, type RefObject } from "react";
import type { AssistantRuntime } from "@assistant-ui/react";
import type { Agent } from "@/types/agentConfig";
import { conversationService } from "@/services/conversationService";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";
import log from "@/lib/logger";

export function useConversationResume({
  runtime,
  activeConversationId,
  activeThreadId,
  ready,
  isThreadRunning,
  selectedAgent,
  chatMode,
  resumedConversationIdsRef,
  handleGenerationStopped,
}: {
  runtime: AssistantRuntime;
  activeConversationId: string | undefined;
  activeThreadId: string | undefined;
  ready: boolean;
  isThreadRunning: boolean;
  selectedAgent: Agent | null;
  chatMode: "planning" | "execution";
  resumedConversationIdsRef: RefObject<Set<number>>;
  handleGenerationStopped: (id: number) => void;
}) {
  const pendingResumes = useRef(new Set<number>());
  // A route change tears down the local stream, while the backend keeps the
  // conversation marked as streaming. Reconnect the assistant-ui runtime when
  // the historical load reports that state.
  useEffect(() => {
    const pending = pendingResumes.current;
    const numericConversationId = Number(activeConversationId);
    if (isThreadRunning) {
      resumedConversationIdsRef.current?.delete(numericConversationId);
      return;
    }
    if (
      !ready ||
      isThreadRunning ||
      !activeThreadId ||
      !Number.isInteger(numericConversationId) ||
      numericConversationId <= 0 ||
      resumedConversationIdsRef.current!.has(numericConversationId) ||
      pending.has(numericConversationId)
    ) {
      return;
    }

    let cancelled = false;
    void conversationService
      .getById(String(numericConversationId))
      .then((conversation) => {
        if (
          cancelled ||
          conversation.streaming_message?.status !== "streaming" ||
          resumedConversationIdsRef.current!.has(numericConversationId)
        ) {
          return;
        }

        pending.add(numericConversationId);
        const messages = runtime.thread.getState().messages;
        const parentId = messages.at(-1)?.id ?? null;
        runtime.thread.resumeRun({
          parentId,
          sourceId: null,
          runConfig: {
            custom: {
              threadId: String(numericConversationId),
              ...(selectedAgent?.id ? { agentId: selectedAgent.id } : {}),
              ...(selectedAgent?.current_version_no
                ? { agentVersionNo: selectedAgent.current_version_no }
                : {}),
              onGenerationStopped: handleGenerationStopped,
              enablePlan: chatMode === "planning",
              resume: true,
            },
          },
          stream: async function* (options) {
            const resumedRun = remoteChatModelAdapter.run(options);
            if (Symbol.asyncIterator in resumedRun) {
              yield* resumedRun;
            } else {
              yield await resumedRun;
            }
          },
        });
      })
      .catch((error) => {
        if (!cancelled) {
          pending.delete(numericConversationId);
          log.error(
            `[HomeContent] Failed to resume conversation ${numericConversationId}:`,
            error
          );
        }
      });

    return () => {
      cancelled = true;
      pending.delete(numericConversationId);
    };
  }, [
    activeConversationId,
    activeThreadId,
    chatMode,
    isThreadRunning,
    ready,
    runtime,
    selectedAgent,
    handleGenerationStopped,
    resumedConversationIdsRef,
  ]);
}
