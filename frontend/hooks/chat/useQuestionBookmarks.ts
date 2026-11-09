// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { conversationService } from "@/services/conversationService";

export function useQuestionBookmarks(conversationId?: number, enabled = true) {
  const { user } = useAuthorizationContext();
  const client = useQueryClient();
  const saving = useRef(false);
  const queryKey = [
    "question-bookmarks",
    user?.id,
    user?.tenantId,
    conversationId,
  ];
  const available = Boolean(
    enabled &&
    user?.id &&
    user?.tenantId &&
    conversationId &&
    conversationId > 0
  );
  const query = useQuery({
    queryKey,
    enabled: available,
    queryFn: () => conversationService.getQuestionBookmarks(conversationId!),
  });
  const mutation = useMutation({
    mutationFn: ({
      messageId,
      bookmarked,
      conversation,
    }: {
      messageId: number;
      bookmarked: boolean;
      conversation: number;
      key: typeof queryKey;
    }) =>
      conversationService.setQuestionBookmark(
        conversation,
        messageId,
        bookmarked
      ),
    // Mutation variables retain their original scope if the user switches chats.
    onSuccess: (ids, variables) => client.setQueryData(variables.key, ids),
    onSettled: () => {
      saving.current = false;
    },
  });
  const sameMutationScope = mutation.variables?.key.every(
    (value, index) => value === queryKey[index]
  );
  return {
    ids: query.data ?? [],
    enabled: available,
    ready: available && query.isSuccess && !query.isFetching,
    pending: mutation.isPending,
    failed: query.isError || Boolean(sameMutationScope && mutation.isError),
    retry: () => {
      mutation.reset();
      void query.refetch();
    },
    toggle: (messageId: number, bookmarked: boolean) => {
      if (
        available &&
        query.isSuccess &&
        !query.isFetching &&
        !saving.current
      ) {
        saving.current = true;
        mutation.mutate({
          messageId,
          bookmarked,
          conversation: conversationId!,
          key: queryKey,
        });
      }
    },
  };
}
