import { useQuery } from "@tanstack/react-query";
import { listTenants } from "@/services/tenantService";

export function useTenantList() {
  return useQuery({
    queryKey: ["tenants"],
    queryFn: () => listTenants(),
    staleTime: 1000 * 60, // Cache for 1 minute
  });
}
