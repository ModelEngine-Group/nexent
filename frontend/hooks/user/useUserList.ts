import { useQuery } from "@tanstack/react-query";
import { listUsers } from "@/services/userService";

export function useUserList(
  tenantId: string | null,
  page?: number,
  pageSize?: number,
  filters?: { search?: string; roles?: string[]; groupIds?: number[] }
) {
  return useQuery({
    queryKey: ["users", tenantId, page, pageSize, filters],
    queryFn: () => listUsers(tenantId, page, pageSize, filters),
    enabled: tenantId !== null,
    staleTime: 1000 * 30,
    refetchOnMount: "always", // Always refetch when component mounts (e.g., when switching tabs)
  });
}
