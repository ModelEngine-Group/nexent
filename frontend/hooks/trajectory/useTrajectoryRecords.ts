// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useCallback, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { trajectoryService } from "@/services/trajectoryService";
import type { RecordsRequest } from "@/types/trajectory";

export function useTrajectoryRecords(scope: string, params: RecordsRequest) {
  const [revision, setRevision] = useState(0);
  const membership = useRef<{ filterKey: string; id: string } | null>(null);
  const { page, page_size, sort_by, sort_order, ...filters } = params;
  const filterKey = JSON.stringify([scope, filters, revision]);
  const result = useQuery({
    queryKey: ["trajectory-records", scope, params, revision],
    queryFn: async ({ signal }) => {
      const query_id =
        membership.current?.filterKey === filterKey
          ? membership.current.id
          : undefined;
      const data = await trajectoryService.records(
        { ...filters, page, page_size, sort_by, sort_order, query_id },
        signal
      );
      if (!signal.aborted)
        membership.current = { filterKey, id: data.query_id };
      return data;
    },
    retry: false,
    gcTime: 0,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const refresh = useCallback(() => {
    membership.current = null;
    setRevision((value) => value + 1);
  }, []);
  return { ...result, refresh };
}
