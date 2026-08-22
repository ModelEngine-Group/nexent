import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { modelService } from "@/services/modelService";
import { CapacityCoverage } from "@/types/modelConfig";

const EMPTY_COVERAGE: CapacityCoverage = {
  totalLlmVlm: 0,
  bareCount: 0,
  bareModels: [],
};

export function useCapacityCoverage(options?: {
  enabled?: boolean;
  staleTime?: number;
}) {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["modelCapacityCoverage"],
    queryFn: async (): Promise<CapacityCoverage> =>
      modelService.getCapacityCoverage(),
    staleTime: options?.staleTime ?? 60_000,
    enabled: options?.enabled ?? true,
  });

  const coverage = query.data ?? EMPTY_COVERAGE;

  const bareModelIds = useMemo(
    () => new Set(coverage.bareModels.map((m) => m.modelId)),
    [coverage]
  );

  const suggestionAvailableModelIds = useMemo(
    () =>
      new Set(
        coverage.bareModels
          .filter((m) => m.suggestionAvailable)
          .map((m) => m.modelId)
      ),
    [coverage]
  );

  return {
    ...query,
    coverage,
    bareModelIds,
    suggestionAvailableModelIds,
    invalidate: () =>
      queryClient.invalidateQueries({ queryKey: ["modelCapacityCoverage"] }),
  };
}
