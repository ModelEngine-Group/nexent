"use client";

import { API_ENDPOINTS } from "./api";
import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";
import type {
  ModelMonitoringItem,
  ModelSummaryResponse,
  TrendPoint,
  FailureDetail,
  AlertRecord,
  PaginatedData,
  MonitoringFilter,
  TrendFilter,
  AlertFilter,
} from "@/types/monitoring";

const EMPTY_PAGINATED = <T,>(): PaginatedData<T> => ({
  items: [],
  total: 0,
  page: 1,
  page_size: 20,
  total_pages: 0,
});

function buildQueryString(params: Record<string, string | number | undefined>): string {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") qs.append(key, String(value));
  });
  const str = qs.toString();
  return str ? `?${str}` : "";
}

export const monitoringService = {
  fetchModels: async (filter?: MonitoringFilter): Promise<ModelMonitoringItem[]> => {
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

  fetchAggregatedTrend: async (filter?: TrendFilter & { model_id?: string }): Promise<TrendPoint[]> => {
    try {
      const qs = buildQueryString({
        interval: filter?.interval,
        time_range: filter?.time_range,
        model_id: filter?.model_id,
      });
      const response = await fetch(`${API_ENDPOINTS.monitoring.trend}${qs}`, {
        headers: getAuthHeaders(),
      });
      const result = await response.json();
      return result.code === 0 && result.data ? result.data : [];
    } catch (error) {
      log.warn("Failed to fetch aggregated trend:", error);
      return [];
    }
  },

  fetchModelSummary: async (modelId: string): Promise<ModelSummaryResponse | null> => {
    try {
      const response = await fetch(API_ENDPOINTS.monitoring.modelSummary(modelId), {
        headers: getAuthHeaders(),
      });
      const result = await response.json();
      return result.code === 0 && result.data ? result.data : null;
    } catch (error) {
      log.warn("Failed to fetch model summary:", error);
      return null;
    }
  },

  fetchModelTrend: async (modelId: string, filter?: TrendFilter): Promise<TrendPoint[]> => {
    try {
      const qs = buildQueryString({
        interval: filter?.interval,
        time_range: filter?.time_range,
      });
      const response = await fetch(`${API_ENDPOINTS.monitoring.modelTrend(modelId)}${qs}`, {
        headers: getAuthHeaders(),
      });
      const result = await response.json();
      return result.code === 0 && result.data ? result.data : [];
    } catch (error) {
      log.warn("Failed to fetch model trend:", error);
      return [];
    }
  },

  fetchModelFailures: async (modelId: string, filter?: MonitoringFilter): Promise<PaginatedData<FailureDetail>> => {
    try {
      const qs = buildQueryString({
        page: filter?.page,
        page_size: filter?.page_size,
      });
      const response = await fetch(`${API_ENDPOINTS.monitoring.modelFailures(modelId)}${qs}`, {
        headers: getAuthHeaders(),
      });
      const result = await response.json();
      return result.code === 0 && result.data ? result.data : EMPTY_PAGINATED();
    } catch (error) {
      log.warn("Failed to fetch model failures:", error);
      return EMPTY_PAGINATED();
    }
  },

  fetchAlerts: async (filter?: AlertFilter): Promise<PaginatedData<AlertRecord>> => {
    try {
      const qs = buildQueryString({
        status: filter?.status,
        severity: filter?.severity,
        type: filter?.type,
        page: filter?.page,
        page_size: filter?.page_size,
      });
      const response = await fetch(`${API_ENDPOINTS.monitoring.alerts}${qs}`, {
        headers: getAuthHeaders(),
      });
      const result = await response.json();
      return result.code === 0 && result.data ? result.data : EMPTY_PAGINATED();
    } catch (error) {
      log.warn("Failed to fetch alerts:", error);
      return EMPTY_PAGINATED();
    }
  },

  acknowledgeAlert: async (alertId: string): Promise<boolean> => {
    try {
      const response = await fetch(API_ENDPOINTS.monitoring.acknowledgeAlert(alertId), {
        method: "PUT",
        headers: getAuthHeaders(),
      });
      const result = await response.json();
      return result.code === 0;
    } catch (error) {
      log.warn("Failed to acknowledge alert:", error);
      return false;
    }
  },

  resolveAlert: async (alertId: string): Promise<boolean> => {
    try {
      const response = await fetch(API_ENDPOINTS.monitoring.resolveAlert(alertId), {
        method: "PUT",
        headers: getAuthHeaders(),
      });
      const result = await response.json();
      return result.code === 0;
    } catch (error) {
      log.warn("Failed to resolve alert:", error);
      return false;
    }
  },
};
