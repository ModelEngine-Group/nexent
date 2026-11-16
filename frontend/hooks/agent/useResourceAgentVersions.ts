// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { fetchAgentVersionList } from "@/services/agentVersionService";
import type { AgentVersion } from "@/services/agentVersionService";

export function useResourceAgentVersions(tenantId: string | null) {
  const queryClient = useQueryClient();
  const [state, setState] = useState({
    tenantId,
    generation: 0,
    versions: new Map<number, AgentVersion[]>(),
    loading: new Map<number, boolean>(),
  });
  if (state.tenantId !== tenantId) {
    setState({
      tenantId,
      generation: state.generation + 1,
      versions: new Map(),
      loading: new Map(),
    });
  }
  const current = state.tenantId === tenantId;

  const loadVersions = async (agentId: number) => {
    const generation = state.generation;
    const update = (mutate: (value: typeof state) => typeof state) => {
      setState((previous) =>
        previous.generation === generation && previous.tenantId === tenantId
          ? mutate(previous)
          : previous
      );
    };
    update((previous) => ({
      ...previous,
      loading: new Map(previous.loading).set(agentId, true),
    }));
    try {
      const result = await queryClient.fetchQuery({
        queryKey: ["agentVersions", agentId, tenantId ?? undefined],
        queryFn: async () => {
          const response = await fetchAgentVersionList(
            agentId,
            tenantId ?? undefined
          );
          if (!response.success) throw new Error(response.message);
          return response.data;
        },
        staleTime: 60_000,
      });
      update((previous) => ({
        ...previous,
        versions: new Map(previous.versions).set(agentId, result.items || []),
      }));
    } finally {
      update((previous) => ({
        ...previous,
        loading: new Map(previous.loading).set(agentId, false),
      }));
    }
  };

  return {
    agentVersions: current ? state.versions : new Map<number, AgentVersion[]>(),
    loadingVersions: current ? state.loading : new Map<number, boolean>(),
    loadVersions,
  };
}
