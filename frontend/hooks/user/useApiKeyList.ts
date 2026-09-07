import { useQuery } from "@tanstack/react-query";
import { listTenantApiKeys } from "@/services/apiKeyService";

export function useApiKeyList(
  tenantId: string | null,
  page: number,
  pageSize: number
) {
  return useQuery({
    queryKey: ["tenant-api-keys", tenantId, page, pageSize],
    queryFn: () => listTenantApiKeys(tenantId as string, page, pageSize),
    enabled: Boolean(tenantId),
    staleTime: 30_000,
    refetchOnMount: "always",
  });
}
