import { useQuery } from "@tanstack/react-query";
import { modelService } from "@/services/modelService";
import { ModelOption } from "@/types/modelConfig";

export interface ManageTenantModelResult {
  models: ModelOption[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
  tenantName: string;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
}

export function useManageTenantModels(options: {
  tenantId: string;
  modelType?: string;
  page?: number;
  pageSize?: number;
  enabled?: boolean;
}): ManageTenantModelResult {
  const { tenantId, modelType, page = 1, pageSize = 20, enabled = true } = options;

  const query = useQuery({
    queryKey: ["manage-tenant-models", tenantId, modelType, page, pageSize],
    queryFn: async (): Promise<{
      models: ModelOption[];
      total: number;
      page: number;
      pageSize: number;
      totalPages: number;
      tenantName: string;
    }> => {
      const result = await modelService.getManageTenantModels({
        tenantId,
        modelType,
        page,
        pageSize,
      });
      return result;
    },
    enabled: enabled && !!tenantId,
    staleTime: 30_000, // 30 seconds default
  });

  return {
    models: query.data?.models ?? [],
    total: query.data?.total ?? 0,
    page: query.data?.page ?? 1,
    pageSize: query.data?.pageSize ?? 20,
    totalPages: query.data?.totalPages ?? 0,
    tenantName: query.data?.tenantName ?? "",
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error as Error | null,
    refetch: async () => {
      await query.refetch();
    },
  };
}

