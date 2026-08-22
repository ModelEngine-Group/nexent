import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";

import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";
import {
  PromptTemplate,
  PromptTemplatePayload,
} from "@/types/agentConfig";

async function requestJson<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetchWithErrorHandling(url, {
    ...options,
    headers: {
      ...getAuthHeaders(),
      ...(options.headers || {}),
    },
  });
  return response.json();
}

export const promptTemplateService = {
  async list(): Promise<PromptTemplate[]> {
    try {
      const data = await requestJson<PromptTemplate[]>(API_ENDPOINTS.promptTemplates.list, {
        method: "GET",
      });
      return data || [];
    } catch (error) {
      log.error("Failed to list prompt templates:", error);
      return [];
    }
  },

  async detail(templateId: number): Promise<PromptTemplate | null> {
    try {
      const data = await requestJson<PromptTemplate>(
        API_ENDPOINTS.promptTemplates.detail(templateId),
        { method: "GET" }
      );
      return data;
    } catch (error) {
      log.error("Failed to get prompt template detail:", error);
      return null;
    }
  },

  async create(payload: PromptTemplatePayload): Promise<PromptTemplate | null> {
    try {
      const data = await requestJson<PromptTemplate>(
        API_ENDPOINTS.promptTemplates.create,
        {
          method: "POST",
          body: JSON.stringify(payload),
        }
      );
      return data;
    } catch (error) {
      log.error("Failed to create prompt template:", error);
      throw error;
    }
  },

  async update(templateId: number, payload: PromptTemplatePayload): Promise<PromptTemplate | null> {
    try {
      const data = await requestJson<PromptTemplate>(
        API_ENDPOINTS.promptTemplates.update(templateId),
        {
          method: "PUT",
          body: JSON.stringify(payload),
        }
      );
      return data;
    } catch (error) {
      log.error("Failed to update prompt template:", error);
      throw error;
    }
  },

  async remove(templateId: number): Promise<boolean> {
    try {
      await requestJson(API_ENDPOINTS.promptTemplates.delete(templateId), {
        method: "DELETE",
      });
      return true;
    } catch (error) {
      log.error("Failed to delete prompt template:", error);
      throw error;
    }
  },
};
