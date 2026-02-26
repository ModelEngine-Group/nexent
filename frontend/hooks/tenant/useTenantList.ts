import { useQuery } from "@tanstack/react-query";
import { listTenants, Tenant } from "@/services/tenantService";
import log from "@/lib/logger";

export interface TenantListResult {
  data: Tenant[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export function useTenantList(params?: { page?: number; page_size?: number }) {
  return useQuery({
    queryKey: ["tenants", params?.page ?? 1, params?.page_size ?? 20],
    queryFn: async () => {
      log.info("[useTenantList] Fetching tenants with params:", params);
      const result = await listTenants(params);
      log.info("[useTenantList] Received result:", result);
      // Filter out invalid tenant data without tenant_id
      const validData = (result.data || []).filter(
        (tenant: Tenant) => tenant.tenant_id
      );
      return {
        ...result,
        data: validData,
        total: validData.length,
      };
    },
    staleTime: 1000 * 60, // Cache for 1 minute
  });
}
