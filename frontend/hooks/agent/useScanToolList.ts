// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { updateToolList } from "@/services/mcpService";

/** Discover newly deployed tools before reloading the tenant's cached catalog. */
export function useScanToolList() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const result = await updateToolList();
      if (!result.success) throw new Error(result.message);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["tools"] }),
        queryClient.invalidateQueries({
          queryKey: ["resourceTagMatches", "tool"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["resourceTagAssignments", "tool"],
        }),
      ]);
    },
  });
}
