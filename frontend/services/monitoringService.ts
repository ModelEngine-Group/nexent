"use client";

import { API_ENDPOINTS } from "./api";
import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";
import type {
  ModelMonitoringItem,
  MonitoringFilter,
  MonitoringStatus,
} from "@/types/monitoring";

function buildQueryString(
  params: Record<string, string | number | undefined>
): string {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") qs.append(key, String(value));
  });
  const str = qs.toString();
  return str ? `?${str}` : "";
}

export const monitoringService = {
  fetchStatus: async (): Promise<MonitoringStatus | null> => {
    try {
      const response = await fetch(API_ENDPOINTS.monitoring.status, {
        headers: getAuthHeaders(),
      });
      const result = await response.json();
      return result.code === 0 && result.data ? result.data : null;
    } catch (error) {
      log.warn("Failed to fetch monitoring status:", error);
      return null;
    }
  },

  fetchModels: async (
    filter?: MonitoringFilter
  ): Promise<ModelMonitoringItem[]> => {
    try {
      const qs = buildQueryString({
        time_range: filter?.time_range,
        page: filter?.page,
        page_size: filter?.page_size,
      });
      const response = await fetch(`${API_ENDPOINTS.monitoring.models}${qs}`, {
        headers: getAuthHeaders(),
      });
      const result = await response.json();
      return result.code === 0 && result.data ? result.data : [];
    } catch (error) {
      log.warn("Failed to fetch monitoring models:", error);
      return [];
    }
  },
};
