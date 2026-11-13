// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { trajectoryService } from "@/services/trajectoryService";

export function useCleanupSchedule(scope: string, tenantId: string) {
  const client = useQueryClient();
  const controller = useRef<AbortController | null>(null);
  const key = ["trajectory-cleanup-schedule", scope, tenantId];
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) =>
      trajectoryService.cleanupSchedule(tenantId, signal),
    retry: false,
    gcTime: 0,
    refetchOnWindowFocus: false,
  });
  const mutation = useMutation({
    mutationFn: async (intervalSeconds: number) => {
      controller.current?.abort();
      const request = new AbortController();
      controller.current = request;
      const result = await trajectoryService.saveCleanupSchedule(
        tenantId,
        intervalSeconds,
        request.signal
      );
      if (request.signal.aborted) throw new Error("Aborted");
      return result;
    },
    onSuccess: (result) => client.setQueryData(key, result),
    retry: false,
  });
  useEffect(() => () => controller.current?.abort(), []);
  return { query, mutation };
}
