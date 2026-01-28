import { useQuery } from "@tanstack/react-query";
import { listUsers } from "@/services/userService";

export function useUserList(
  tenantId: string | null,
  page: number = 1,
  pageSize: number = 20
) {
  return useQuery({
    queryKey: ["users", tenantId, page, pageSize],
    queryFn: () => listUsers(tenantId, page, pageSize),
    enabled: tenantId !== null,
    staleTime: 1000 * 30,
    refetchOnMount: "always", // Always refetch when component mounts (e.g., when switching tabs)
  });
}
