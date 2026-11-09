// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useQuestionBookmarks } from "@/hooks/chat/useQuestionBookmarks";
import { useQuery } from "@tanstack/react-query";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { conversationService } from "@/services/conversationService";
import { collapseRefreshUserMessages } from "../adapter/history-branching";
import {
  QuestionDirectoryRail,
  type QuestionDirectoryRailProps,
} from "./question-directory-rail";

export function QuestionBookmarkRail({
  conversationId,
  readOnly,
  isRunning,
  ...props
}: QuestionDirectoryRailProps & {
  conversationId?: number;
  readOnly?: boolean;
  isRunning?: boolean;
}) {
  const bookmarks = useQuestionBookmarks(conversationId, !readOnly);
  const { user } = useAuthorizationContext();
  const runtimeIds = props.questions.map((q) => q.messageId).join(",");
  const needsMapping = props.questions.some(
    (q) => !/^[1-9]\d*$/.test(q.messageId)
  );
  const identities = useQuery({
    queryKey: [
      "question-bookmark-identities",
      user?.id,
      user?.tenantId,
      conversationId,
      runtimeIds,
    ],
    enabled: bookmarks.enabled && needsMapping && !isRunning,
    queryFn: () => conversationService.getDetail(conversationId!),
  });
  const backendMessageIds = new Map<string, number>();
  const stored = collapseRefreshUserMessages(
    identities.data?.data?.[0]?.message ?? []
  ).filter((m) => m.role === "user");
  for (const [index, question] of props.questions.entries()) {
    const numeric = Number(question.messageId);
    const row = stored[index];
    if (
      /^[1-9]\d*$/.test(question.messageId) &&
      Number.isSafeInteger(numeric)
    ) {
      backendMessageIds.set(question.messageId, numeric);
    } else if (
      stored.length === props.questions.length &&
      typeof row?.message === "string" &&
      row.message.trim() === question.fullText.trim()
    ) {
      const id = Number(row.message_id);
      if (Number.isSafeInteger(id) && id > 0)
        backendMessageIds.set(question.messageId, id);
    }
  }
  const saved = new Set(bookmarks.ids);
  return (
    <QuestionDirectoryRail
      {...props}
      bookmarkedIds={
        new Set(
          props.questions
            .filter((q) => saved.has(backendMessageIds.get(q.messageId)!))
            .map((q) => q.messageId)
        )
      }
      onBookmark={
        bookmarks.enabled
          ? (id, marked) => {
              const backendId = backendMessageIds.get(id);
              if (backendId) bookmarks.toggle(backendId, marked);
            }
          : undefined
      }
      canBookmark={(id) =>
        bookmarks.ready && !bookmarks.pending && backendMessageIds.has(id)
      }
      bookmarkFailed={
        bookmarks.failed ||
        identities.isError ||
        Boolean(
          needsMapping &&
          identities.isSuccess &&
          backendMessageIds.size !== props.questions.length
        )
      }
      onBookmarkRetry={() => {
        bookmarks.retry();
        if (needsMapping) void identities.refetch();
      }}
    />
  );
}
