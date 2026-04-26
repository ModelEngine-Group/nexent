"use client";

import { useQuery } from "@tanstack/react-query";
import { API_ENDPOINTS, fetchWithErrorHandling } from "@/services/api";
import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";

export interface WorkflowConfig {
  workflow_enabled: boolean;
  workflow_url: string | null;
}

/**
 * Hook to fetch workflow orchestration configuration
 */
export function useWorkflowConfig() {
  const query = useQuery({
    queryKey: ["workflow-config"],
    queryFn: async () => {
      try {
        const response = await fetchWithErrorHandling(
          API_ENDPOINTS.oauth.workflowConfig,
          {
            method: "GET",
            headers: {
              ...getAuthHeaders(),
            },
          }
        );
        const result = await response.json();
        return result.data as WorkflowConfig;
      } catch (error) {
        log.error("Failed to fetch workflow config:", error);
        return { workflow_enabled: false, workflow_url: null } as WorkflowConfig;
      }
    },
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    retry: 1,
    refetchOnWindowFocus: false,
  });

  return query;
}
