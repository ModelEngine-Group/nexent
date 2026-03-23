import log from "@/lib/logger";

import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";

export interface MeclawOverviewStats {
  running_count: number;
  total_count: number;
  total_token_usage: number;
}

export interface MeclawInstance {
  id: string;
  name: string;
  created_at: string;
  status: string;
  author: string;
  description: string;
}

export interface MeclawInstanceDetail {
  id: string;
  name: string;
  author: string;
  description: string;
  status: string;
  created_at: string;
  model: string;
  skills: string[];
  plugins: string[];
  token_usage: number;
  report_time: string;
  chat_url: string;
  last_report_time: string;
}

/**
 * Fetch meclaw overview statistics
 */
export const getMeclawOverview = async (): Promise<{
  success: boolean;
  data: MeclawOverviewStats | null;
  message: string;
}> => {
  try {
    const response = await fetchWithErrorHandling(API_ENDPOINTS.meclaw.overview);
    const data: MeclawOverviewStats = await response.json();
    return { success: true, data, message: "" };
  } catch (error) {
    log.error("Failed to fetch meclaw overview", error);
    return { success: false, data: null, message: String(error) };
  }
};

/**
 * Fetch the list of meclaw instances
 */
export const getMeclawInstances = async (): Promise<{
  success: boolean;
  data: MeclawInstance[];
  message: string;
}> => {
  try {
    const response = await fetchWithErrorHandling(API_ENDPOINTS.meclaw.instances);
    const data: MeclawInstance[] = await response.json();
    return { success: true, data, message: "" };
  } catch (error) {
    log.error("Failed to fetch meclaw instances", error);
    return { success: false, data: [], message: String(error) };
  }
};

/**
 * Fetch detail of a single meclaw instance by ID
 */
export const getMeclawInstanceDetail = async (
  instanceId: string
): Promise<{
  success: boolean;
  data: MeclawInstanceDetail | null;
  message: string;
}> => {
  try {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.meclaw.instanceDetail(instanceId)
    );
    const data: MeclawInstanceDetail = await response.json();
    return { success: true, data, message: "" };
  } catch (error) {
    log.error("Failed to fetch meclaw instance detail", error);
    return { success: false, data: null, message: String(error) };
  }
};
