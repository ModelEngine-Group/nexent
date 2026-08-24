import { useQuery, useQueryClient } from "@tanstack/react-query";
import { modelService } from "@/services/modelService";

export function useCapacityHealth(options?: { enabled?: boolean }) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["modelCapacityHealth"],
    queryFn: modelService.getCapacityHealth,
    staleTime: 60_000,
    enabled: options?.enabled ?? true,
  });
  return {
    ...query,
    health: query.data,
    invalidate: () =>
      queryClient.invalidateQueries({ queryKey: ["modelCapacityHealth"] }),
  };
}
