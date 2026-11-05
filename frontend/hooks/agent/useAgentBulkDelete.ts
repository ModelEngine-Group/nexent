// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { deleteAgent } from "@/services/agentConfigService";
import type { Agent } from "@/types/agentConfig";

export function useAgentBulkDelete() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (agents: readonly Agent[]) => {
      const deleted: Agent[] = [];
      const failed: Agent[] = [];
      // Reuse the existing single-delete contract without reporting partial failure as success.
      for (const agent of agents) {
        const id = Number(agent.id);
        if (
          agent.permission === "READ_ONLY" ||
          !Number.isInteger(id) ||
          id <= 0
        ) {
          failed.push(agent);
          continue;
        }
        try {
          const result = await deleteAgent(id);
          (result.success ? deleted : failed).push(agent);
        } catch {
          failed.push(agent);
        }
      }
      return { deleted, failed };
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["agents"] }),
        queryClient.invalidateQueries({ queryKey: ["publishedAgentsList"] }),
      ]);
    },
  });
}
