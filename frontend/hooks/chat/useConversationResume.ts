// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useRef, type RefObject } from "react";
import type { AssistantRuntime } from "@assistant-ui/react";
import type { ConversationDetailReader } from "@/types/conversation";
import type { Agent } from "@/types/agentConfig";
import { conversationService } from "@/services/conversationService";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";
import log from "@/lib/logger";
import { RemoteConversationHistoryAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";

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
  loadDetail = conversationService.getById,
  invalidateDetail,
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
  loadDetail?: ConversationDetailReader;
  invalidateDetail?: (id: string) => void;
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
      if (numericConversationId > 0)
        invalidateDetail?.(String(numericConversationId));
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
    void loadDetail(String(numericConversationId))
      .then(async (conversation) => {
        if (
          cancelled ||
          conversation.streaming_message?.status !== "streaming" ||
          resumedConversationIdsRef.current!.has(numericConversationId)
        ) {
          return;
        }

        pending.add(numericConversationId);
        const remoteId = String(numericConversationId);
        const history = new RemoteConversationHistoryAdapter(
          () => remoteId,
          async () => ({ remoteId }),
          async () => conversation
        );
        const repository = await history.load();
        if (cancelled || runtime.thread.getState().isRunning) return;
        const streamingId = String(conversation.streaming_message.message_id);
        const streaming = repository.messages.find(
          (entry) => entry.message.id === streamingId
        );
        const parent = repository.messages.find(
          (entry) => entry.message.id === streaming?.parentId
        );
        if (
          streaming?.message.role !== "assistant" ||
          parent?.message.role !== "user"
        ) {
          throw new Error("Streaming answer has no originating user message");
        }
        const streamingMessage = streaming.message;
        const parentId = parent.message.id;
        // resumeRun creates a new assistant. Replace only the persisted running
        // branch so it remains a sibling of earlier retries, never their child.
        runtime.thread.import({
          ...repository,
          messages: repository.messages.filter(
            (entry) => entry.message.id !== streamingId
          ),
          // Importing with the user as head would prune all its answer branches.
          headId:
            repository.messages.findLast(
              (entry) =>
                entry.parentId === parentId && entry.message.id !== streamingId
            )?.message.id ?? parentId,
        });
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
            // Preserve the persisted output until the server replays the stream.
            yield {
              content: streamingMessage.content,
              metadata: streamingMessage.metadata,
            };
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
    loadDetail,
    invalidateDetail,
  ]);
}
