// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { QueryClient } from "@tanstack/react-query";
import type { WorkbenchPins } from "@/types/conversation";

export const workbenchPinsQueryKey = (scope: string | null | undefined) =>
  ["workbench-pins", scope] as const;

/** Remove confirmed deletions before history reload can hydrate cached pins. */
export async function removeDeletedWorkbenchPins(
  client: QueryClient,
  conversationIds: readonly number[],
  failedIds: readonly number[] = []
) {
  const failed = new Set(failedIds);
  const deleted = new Set(conversationIds.filter((id) => !failed.has(id)));
  if (deleted.size === 0) return;

  const filters = { queryKey: ["workbench-pins"] };
  await client.cancelQueries(filters);
  client.setQueriesData<WorkbenchPins>(filters, (pins) =>
    pins
      ? {
          ...pins,
          items: pins.items.filter(
            (item) => !deleted.has(item.conversation_id)
          ),
        }
      : pins
  );
}
