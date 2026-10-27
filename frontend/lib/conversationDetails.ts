// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { QueryClient } from "@tanstack/react-query";
import { conversationService } from "@/services/conversationService";
import type {
  ApiConversationDetail,
  ConversationDetailLoader,
} from "@/types/conversation";

let nextScope = 0;

/** Share pending and settled restoration reads until their owning activation ends. */
export function createConversationDetailLoader(
  queryClient: QueryClient,
  identity: string
): ConversationDetailLoader {
  const prefix = ["workbench-conversation-detail", identity, ++nextScope];
  const generations = new Map<string, number>();
  const pending = new Map<string, Promise<ApiConversationDetail>>();
  let activeId: string | undefined;
  const normalize = (id: string | undefined) =>
    id && /^[1-9]\d*$/.test(id) ? id : undefined;
  const key = (id: string, generation: number) => [...prefix, id, generation];
  const invalidate = (id: string) => {
    const generation = generations.get(id) ?? 0;
    generations.set(id, generation + 1);
    pending.delete(id);
    // Departure must not cancel another consumer of the pending result.
    const queryKey = key(id, generation);
    if (queryClient.getQueryState(queryKey)?.fetchStatus !== "fetching") {
      queryClient.removeQueries({ queryKey, exact: true });
    }
  };
  const load = (conversationId: string) => {
    const id = normalize(conversationId);
    if (!id) return Promise.reject(new Error("Invalid conversation ID"));
    const existing = pending.get(id);
    if (existing) return existing;
    const generation = generations.get(id) ?? 0;
    const queryKey = key(id, generation);
    const result = queryClient
      .fetchQuery({
        queryKey,
        queryFn: () => conversationService.getById(id),
        staleTime: Infinity,
        gcTime: 5 * 60_000,
        retry: false,
      })
      .finally(() => {
        if ((generations.get(id) ?? 0) !== generation) {
          queryClient.removeQueries({ queryKey, exact: true });
        }
      });
    // A later restore stage must not independently retry a failed read either.
    pending.set(id, result);
    return result;
  };
  return {
    load,
    refresh: (id) => {
      invalidate(id);
      return load(id);
    },
    invalidate,
    activate: (conversationId) => {
      const id = normalize(conversationId);
      if (activeId === id) return;
      if (activeId) invalidate(activeId);
      activeId = id;
    },
    clear: () => {
      for (const id of pending.keys()) invalidate(id);
      queryClient.removeQueries({ queryKey: prefix });
      activeId = undefined;
    },
  };
}
