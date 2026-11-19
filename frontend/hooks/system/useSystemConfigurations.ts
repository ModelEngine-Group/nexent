// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  listSystemConfigurations,
  saveSystemConfigurations,
} from "@/services/systemConfigurationService";
import type {
  SystemConfigurationChanges,
  SystemConfigurationListResponse,
} from "@/types/systemConfiguration";

const SYSTEM_CONFIGURATIONS_KEY = ["systemConfigurations"] as const;

export function useSystemConfigurations() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: SYSTEM_CONFIGURATIONS_KEY,
    queryFn: ({ signal }) => listSystemConfigurations(signal),
    staleTime: 10_000,
  });
  const mutation = useMutation({
    mutationFn: (changes: SystemConfigurationChanges) =>
      saveSystemConfigurations(changes),
    onSuccess: (result) => {
      const saved = new Map(result.items.map((item) => [item.key, item]));
      queryClient.setQueryData<SystemConfigurationListResponse>(
        SYSTEM_CONFIGURATIONS_KEY,
        (current) =>
          current
            ? {
                ...current,
                items: current.items.map((item) => saved.get(item.key) ?? item),
              }
            : current
      );
      void queryClient.invalidateQueries({
        queryKey: SYSTEM_CONFIGURATIONS_KEY,
      });
    },
  });

  return { ...query, saveMutation: mutation };
}
