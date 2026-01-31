import { useQuery } from "@tanstack/react-query";
import { listGroups } from "@/services/groupService";

export function useGroupList(tenantId: string | null, page: number = 1, pageSize: number = 20) {
  return useQuery({
    queryKey: ["groups", tenantId, page, pageSize],
    queryFn: () => listGroups(tenantId!, page, pageSize),
    enabled: tenantId !== null,
    staleTime: 1000 * 30,
    refetchOnMount: 'always', // Always refetch when component mounts (e.g., when switching tabs)
  });
}
