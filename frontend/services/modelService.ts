"use client";

import { API_ENDPOINTS } from "./api";

import {
  ModelOption,
  ModelType,
  ModelConnectStatus,
  ModelValidationResponse,
  ModelSource,
} from "@/types/modelConfig";

import { getAuthHeaders } from "@/lib/auth";
import { STATUS_CODES } from "@/const/auth";
import {
  MODEL_TYPES,
  MODEL_SOURCES,
  MODEL_PROVIDER_KEYS,
  PROVIDER_HINTS,
  PROVIDER_ICON_MAP,
  DEFAULT_PROVIDER_ICON,
  OFFICIAL_PROVIDER_ICON,
  ModelProviderKey,
} from "@/const/modelConfig";
import log from "@/lib/logger";

// Error class
export class ModelError extends Error {
  constructor(message: string, public code?: number) {
    super(message);
    this.name = "ModelError";
    // Override the stack property to only return the message
    Object.defineProperty(this, "stack", {
      get: function () {
        return this.message;
      },
    });
  }

  // Override the toString method to only return the message
  toString() {
    return this.message;
  }
}

// Model service
export const modelService = {
  // Get all models (unified method)
  getAllModels: async (): Promise<ModelOption[]> => {
    try {
      const response = await fetch(API_ENDPOINTS.model.customModelList, {
        headers: getAuthHeaders(),
      });
      const result = await response.json();

      if (response.status === STATUS_CODES.SUCCESS && result.data) {
        return result.data.map((model: any) => ({
          id: model.model_id,
          name: model.model_name,
          type: model.model_type as ModelType,
          maxTokens: model.max_tokens || 0,
          source: model.model_factory as ModelSource,
          apiKey: model.api_key,
          apiUrl: model.base_url,
          displayName: model.display_name || model.model_name,
          connect_status:
            (model.connect_status as ModelConnectStatus) || "not_detected",
          expectedChunkSize: model.expected_chunk_size,
          maximumChunkSize: model.maximum_chunk_size,
          chunkingBatchSize: model.chunk_batch,
        }));
      }
      return [];
    } catch (error) {
      log.warn("Failed to load models:", error);
      return [];
    }
  },

  // Legacy methods for backward compatibility (will be removed after refactoring)
  getOfficialModels: async (): Promise<ModelOption[]> => {
    const allModels = await modelService.getAllModels();
    return allModels.filter((model) => model.source === "modelengine");
  },

  getCustomModels: async (): Promise<ModelOption[]> => {
    const allModels = await modelService.getAllModels();
    return allModels.filter((model) => model.source !== "modelengine");
  },

  // Add custom model
  addCustomModel: async (model: {
    name: string;
    type: ModelType;
    url: string;
    apiKey: string;
    maxTokens: number;
    displayName?: string;
    expectedChunkSize?: number;
    maximumChunkSize?: number;
    chunkingBatchSize?: number;
  }): Promise<void> => {
    try {
      const response = await fetch(API_ENDPOINTS.model.customModelCreate, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          model_repo: "",
          model_name: model.name,
          model_type: model.type,
          base_url: model.url,
          api_key: model.apiKey,
          max_tokens: model.maxTokens,
          display_name: model.displayName,
          expected_chunk_size: model.expectedChunkSize,
          maximum_chunk_size: model.maximumChunkSize,
          chunk_batch: model.chunkingBatchSize,
        }),
      });

      const result = await response.json();

      if (response.status !== 200) {
        throw new ModelError(
          result.detail || result.message || "添加自定义模型失败",
          response.status
        );
      }
    } catch (error) {
      if (error instanceof ModelError) throw error;
      throw new ModelError("添加自定义模型失败", 500);
    }
  },

  addProviderModel: async (model: {
    provider: string;
    type: ModelType;
    apiKey: string;
    baseUrl?: string;
  }): Promise<any[]> => {
    try {
      const response = await fetch(
        API_ENDPOINTS.model.customModelCreateProvider,
        {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify({
            provider: model.provider,
            model_type: model.type,
            api_key: model.apiKey,
            ...(model.baseUrl ? { base_url: model.baseUrl } : {}),
          }),
        }
      );

      const result = await response.json();

      if (response.status !== 200) {
        throw new ModelError(
          result.detail || result.message || "添加自定义模型失败",
          response.status
        );
      }
      return result.data || [];
    } catch (error) {
      if (error instanceof ModelError) throw error;
      throw new ModelError("添加自定义模型失败", 500);
    }
  },

  addBatchCustomModel: async (model: {
    api_key: string;
    provider: string;
    type: ModelType;
    models: any[];
  }): Promise<number> => {
    try {
      const response = await fetch(API_ENDPOINTS.model.customModelBatchCreate, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          api_key: model.api_key,
          models: model.models,
          type: model.type,
          provider: model.provider,
        }),
      });
      const result = await response.json();

      if (response.status !== 200) {
        throw new ModelError(
          result.detail || result.message || "添加自定义模型失败",
          response.status
        );
      }
      return response.status;
    } catch (error) {
      if (error instanceof ModelError) throw error;
      throw new ModelError("添加自定义模型失败", 500);
    }
  },

  getProviderSelectedModalList: async (model: {
    provider: string;
    type: ModelType;
    api_key: string;
    baseUrl?: string;
  }): Promise<any[]> => {
    try {
      const response = await fetch(
        API_ENDPOINTS.model.getProviderSelectedModalList,
        {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify({
            provider: model.provider,
            model_type: model.type,
            api_key: model.api_key,
            ...(model.baseUrl ? { base_url: model.baseUrl } : {}),
          }),
        }
      );
      log.log("getProviderSelectedModalList response", response);
      const result = await response.json();
      log.log("getProviderSelectedModalList result", result);
      if (response.status !== 200) {
        throw new ModelError(
          result.detail || result.message || "获取模型列表失败",
          response.status
        );
      }
      return result.data || [];
    } catch (error) {
      log.log("getProviderSelectedModalList error", error);
      if (error instanceof ModelError) throw error;
      throw new ModelError("获取模型列表失败", 500);
    }
  },

  // List provider models for a specific tenant (admin/manage operation)
  getManageProviderModelList: async (params: {
    tenantId: string;
    provider: string;
    modelType: string;
    apiKey?: string;
    baseUrl?: string;
  }): Promise<any[]> => {
    try {
      const response = await fetch(
        API_ENDPOINTS.model.manageProviderModelList,
        {
          method: "POST",
          headers: {
            ...getAuthHeaders(),
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            tenant_id: params.tenantId,
            provider: params.provider,
            model_type: params.modelType,
            ...(params.apiKey ? { api_key: params.apiKey } : {}),
            ...(params.baseUrl ? { base_url: params.baseUrl } : {}),
          }),
        }
      );
      log.log("getManageProviderModelList response", response);
      const result = await response.json();
      log.log("getManageProviderModelList result", result);
      if (response.status !== 200) {
        throw new ModelError(
          result.detail || result.message || "Failed to get provider model list",
          response.status
        );
      }
      return result.data || [];
    } catch (error) {
      log.log("getManageProviderModelList error", error);
      if (error instanceof ModelError) throw error;
      throw new ModelError("Failed to get provider model list", 500);
    }
  },

  updateSingleModel: async (model: {
    currentDisplayName: string;
    displayName?: string;
    url: string;
    apiKey: string;
    maxTokens?: number;
    source?: ModelSource;
    expectedChunkSize?: number;
    maximumChunkSize?: number;
    chunkingBatchSize?: number;
  }): Promise<void> => {
    try {
      const response = await fetch(
        API_ENDPOINTS.model.updateSingleModel(model.currentDisplayName),
        {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify({
            ...(model.displayName !== undefined
              ? { display_name: model.displayName }
              : {}),
            base_url: model.url,
            api_key: model.apiKey,
            ...(model.maxTokens !== undefined
              ? { max_tokens: model.maxTokens }
              : {}),
            model_factory: model.source || "OpenAI-API-Compatible",
            ...(model.expectedChunkSize !== undefined
              ? { expected_chunk_size: model.expectedChunkSize }
              : {}),
            ...(model.maximumChunkSize !== undefined
              ? { maximum_chunk_size: model.maximumChunkSize }
              : {}),
            ...(model.chunkingBatchSize !== undefined
              ? { chunk_batch: model.chunkingBatchSize }
              : {}),
          }),
        }
      );
      const result = await response.json();
      if (response.status !== 200) {
        throw new ModelError(
          result.detail || result.message || "Failed to update the custom model",
          response.status
        );
      }
    } catch (error) {
      if (error instanceof ModelError) throw error;
      throw new ModelError("Failed to update the custom model", 500);
    }
  },

  updateBatchModel: async (
    models: {
      model_id: string;
      apiKey: string;
      maxTokens?: number;
    }[],
    provider?: string
  ): Promise<any> => {
    try {
      const response = await fetch(API_ENDPOINTS.model.updateBatchModel, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify(
          models.map((m) => ({
            model_id: m.model_id,
            api_key: m.apiKey,
            ...(m.maxTokens !== undefined ? { max_tokens: m.maxTokens } : {}),
            ...(provider ? { model_factory: provider } : {}),
          }))
        ),
      });
      const result = await response.json();
      if (response.status !== 200) {
        throw new ModelError(
          result.detail || result.message || "Failed to update the custom model",
          response.status
        );
      }
      return result;
    } catch (error) {
      if (error instanceof ModelError) throw error;
      throw new ModelError("Failed to update the custom model", 500);
    }
  },

  // Delete custom model
  deleteCustomModel: async (
    displayName: string,
    provider?: string
  ): Promise<void> => {
    try {
      const baseUrl = API_ENDPOINTS.model.customModelDelete(displayName);
      const url = provider
        ? `${baseUrl}&provider=${encodeURIComponent(provider)}`
        : baseUrl;
      const response = await fetch(url, {
        method: "POST",
        headers: getAuthHeaders(),
      });
      const result = await response.json();
      if (response.status !== 200) {
        throw new ModelError(
          result.detail || result.message || "删除自定义模型失败",
          response.status
        );
      }
    } catch (error) {
      if (error instanceof ModelError) throw error;
      throw new ModelError("删除自定义模型失败", 500);
    }
  },

  // Verify custom model connection
  verifyCustomModel: async (
    displayName: string,
    signal?: AbortSignal
  ): Promise<boolean> => {
    try {
      if (!displayName) return false;
      const response = await fetch(
        API_ENDPOINTS.model.customModelHealthcheck(displayName),
        {
          method: "POST",
          headers: getAuthHeaders(),
          signal,
        }
      );
      const result = await response.json();
      if (response.status === 200 && result.data) {
        return result.data.connectivity;
      }
      return false;
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        log.warn(`验证模型 ${displayName} 连接被取消`);
        throw error;
      }
      log.error(`验证模型 ${displayName} 连接失败:`, error);
      return false;
    }
  },

  // Check model connectivity for a specific tenant (admin/manage operation)
  checkManageTenantModelConnectivity: async (
    tenantId: string,
    displayName: string,
    signal?: AbortSignal
  ): Promise<boolean> => {
    try {
      if (!displayName) return false;
      const response = await fetch(API_ENDPOINTS.model.manageModelHealthcheck, {
        method: "POST",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          tenant_id: tenantId,
          display_name: displayName,
        }),
        signal,
      });
      const result = await response.json();
      if (response.status === 200 && result.data) {
        return result.data.connectivity;
      }
      return false;
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        log.warn(`验证模型 ${displayName} (租户: ${tenantId}) 连接被取消`);
        throw error;
      }
      log.error(`验证模型 ${displayName} (租户: ${tenantId}) 连接失败:`, error);
      return false;
    }
  },

  // Verify model configuration connectivity before adding it
  verifyModelConfigConnectivity: async (
    config: {
      modelName: string;
      modelType: ModelType;
      baseUrl: string;
      apiKey: string;
      maxTokens?: number;
      embeddingDim?: number;
    },
    signal?: AbortSignal
  ): Promise<ModelValidationResponse> => {
    try {
      const response = await fetch(API_ENDPOINTS.model.verifyModelConfig, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          model_name: config.modelName,
          model_type: config.modelType,
          base_url: config.baseUrl,
          api_key: config.apiKey || "sk-no-api-key",
          max_tokens: config.maxTokens || 4096,
          embedding_dim: config.embeddingDim || 1024,
        }),
        signal,
      });

      const result = await response.json();

      if (response.status === 200 && result.data) {
        return {
          connectivity: result.data.connectivity,
          model_name: result.data.model_name || "UNKNOWN_MODEL",
          error: result.data.connectivity ? undefined : result.data.error || result.detail || result.message,
        };
      }

      return {
        connectivity: false,
        model_name: result.data?.model_name || "UNKNOWN_MODEL",
        error: result.detail || result.message || "Connection verification failed",
      };
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        log.warn("Model configuration connectivity verification cancelled");
        throw error;
      }
      log.error("Model configuration connectivity verification failed:", error);
      return {
        connectivity: false,
        model_name: "UNKNOWN_MODEL",
        error: error instanceof Error ? error.message : String(error),
      };
    }
  },

  // Get LLM model list for generation
  getLLMModels: async (): Promise<ModelOption[]> => {
    try {
      const response = await fetch(API_ENDPOINTS.model.llmModelList, {
        headers: getAuthHeaders(),
      });
      const result = await response.json();

      if (response.status === STATUS_CODES.SUCCESS && result.data) {
        // Return all models, not just available ones
        return result.data.map((model: any) => ({
          id: model.model_id || model.id,
          name: model.model_name || model.name,
          type: MODEL_TYPES.LLM,
          maxTokens: model.max_tokens || 0,
          source: model.model_factory || MODEL_SOURCES.OPENAI_API_COMPATIBLE,
          apiKey: model.api_key || "",
          apiUrl: model.base_url || "",
          displayName: model.display_name || model.model_name || model.name,
          connect_status: model.connect_status as ModelConnectStatus,
        }));
      }

      return [];
    } catch (error) {
      log.warn("Failed to load LLM models:", error);
      return [];
    }
  },

  // Manage tenant models (for admin operations with tenant_id)
  getManageTenantModels: async (params: {
    tenantId: string;
    modelType?: string;
    page?: number;
    pageSize?: number;
  }): Promise<{
    models: ModelOption[];
    total: number;
    page: number;
    pageSize: number;
    totalPages: number;
    tenantName: string;
  }> => {
    try {
      const response = await fetch(API_ENDPOINTS.model.manageModelList, {
        method: "POST",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          tenant_id: params.tenantId,
          model_type: params.modelType,
          page: params.page || 1,
          page_size: params.pageSize || 20,
        }),
      });
      const result = await response.json();

      if (response.status === STATUS_CODES.SUCCESS && result.data) {
        return {
          models: result.data.models.map((model: any) => ({
            id: model.model_id,
            name: model.model_name,
            type: model.model_type as ModelType,
            maxTokens: model.max_tokens || 0,
            source: model.model_factory as ModelSource,
            apiKey: model.api_key || "",
            apiUrl: model.base_url || "",
            displayName: model.display_name || model.model_name,
            connect_status: model.connect_status as ModelConnectStatus,
            expectedChunkSize: model.expected_chunk_size,
            maximumChunkSize: model.maximum_chunk_size,
            chunkingBatchSize: model.chunk_batch,
          })),
          total: result.data.total || 0,
          page: result.data.page || 1,
          pageSize: result.data.page_size || 20,
          totalPages: result.data.total_pages || 0,
          tenantName: result.data.tenant_name || "",
        };
      }

      return {
        models: [],
        total: 0,
        page: 1,
        pageSize: 20,
        totalPages: 0,
        tenantName: "",
      };
    } catch (error) {
      log.warn("Failed to load manage tenant models:", error);
      return {
        models: [],
        total: 0,
        page: 1,
        pageSize: 20,
        totalPages: 0,
        tenantName: "",
      };
    }
  },

  // Create model for a specific tenant
  createManageTenantModel: async (params: {
    tenantId: string;
    name: string;
    type: ModelType;
    url: string;
    apiKey: string;
    maxTokens?: number;
    displayName?: string;
    expectedChunkSize?: number;
    maximumChunkSize?: number;
    chunkingBatchSize?: number;
  }): Promise<void> => {
    try {
      const response = await fetch(API_ENDPOINTS.model.manageModelCreate, {
        method: "POST",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          tenant_id: params.tenantId,
          model_repo: "",
          model_name: params.name,
          model_type: params.type,
          base_url: params.url,
          api_key: params.apiKey,
          max_tokens: params.maxTokens || 4096,
          display_name: params.displayName || params.name,
          expected_chunk_size: params.expectedChunkSize,
          maximum_chunk_size: params.maximumChunkSize,
          chunk_batch: params.chunkingBatchSize,
        }),
      });

      const result = await response.json();
      if (response.status !== STATUS_CODES.SUCCESS) {
        throw new ModelError(
          result.detail || result.message || "Failed to create model for tenant",
          response.status
        );
      }
    } catch (error) {
      if (error instanceof ModelError) throw error;
      log.warn("Failed to create manage tenant model:", error);
      throw new ModelError("Failed to create model for tenant", 500);
    }
  },

  // Update model for a specific tenant
  updateManageTenantModel: async (params: {
    tenantId: string;
    currentDisplayName: string;
    displayName?: string;
    url: string;
    apiKey: string;
    maxTokens?: number;
    expectedChunkSize?: number;
    maximumChunkSize?: number;
    chunkingBatchSize?: number;
  }): Promise<void> => {
    try {
      const response = await fetch(
        API_ENDPOINTS.model.manageModelUpdate(params.currentDisplayName),
        {
          method: "POST",
          headers: {
            ...getAuthHeaders(),
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            tenant_id: params.tenantId,
            current_display_name: params.currentDisplayName,
            ...(params.displayName !== undefined ? { display_name: params.displayName } : {}),
            base_url: params.url,
            api_key: params.apiKey,
            ...(params.maxTokens !== undefined ? { max_tokens: params.maxTokens } : {}),
            ...(params.expectedChunkSize !== undefined ? { expected_chunk_size: params.expectedChunkSize } : {}),
            ...(params.maximumChunkSize !== undefined ? { maximum_chunk_size: params.maximumChunkSize } : {}),
            ...(params.chunkingBatchSize !== undefined ? { chunk_batch: params.chunkingBatchSize } : {}),
          }),
        }
      );

      const result = await response.json();
      if (response.status !== STATUS_CODES.SUCCESS) {
        throw new ModelError(
          result.detail || result.message || "Failed to update model for tenant",
          response.status
        );
      }
    } catch (error) {
      if (error instanceof ModelError) throw error;
      log.warn("Failed to update manage tenant model:", error);
      throw new ModelError("Failed to update model for tenant", 500);
    }
  },

  // Delete model from a specific tenant
  deleteManageTenantModel: async (params: {
    tenantId: string;
    displayName: string;
  }): Promise<void> => {
    try {
      const response = await fetch(
        API_ENDPOINTS.model.manageModelDelete(params.displayName),
        {
          method: "POST",
          headers: {
            ...getAuthHeaders(),
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            tenant_id: params.tenantId,
            display_name: params.displayName,
          }),
        }
      );

      const result = await response.json();
      if (response.status !== STATUS_CODES.SUCCESS) {
        throw new ModelError(
          result.detail || result.message || "Failed to delete model for tenant",
          response.status
        );
      }
    } catch (error) {
      if (error instanceof ModelError) throw error;
      log.warn("Failed to delete manage tenant model:", error);
      throw new ModelError("Failed to delete model for tenant", 500);
    }
  },

  // Batch create models for a specific tenant
  batchCreateManageTenantModels: async (params: {
    tenantId: string;
    provider: string;
    type: string;
    apiKey: string;
    models: Array<{
      id: string;
      object?: string;
      created?: number;
      owned_by?: string;
      max_tokens?: number;
    }>;
  }): Promise<{ tenantId: string; provider: string; type: string; modelsCount: number }> => {
    try {
      const response = await fetch(API_ENDPOINTS.model.manageModelBatchCreate, {
        method: "POST",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          tenant_id: params.tenantId,
          provider: params.provider,
          type: params.type,
          api_key: params.apiKey,
          models: params.models,
        }),
      });

      const result = await response.json();
      if (response.status !== STATUS_CODES.SUCCESS) {
        throw new ModelError(
          result.detail || result.message || "Failed to batch create models for tenant",
          response.status
        );
      }
      return {
        tenantId: result.data.tenant_id,
        provider: result.data.provider,
        type: result.data.type,
        modelsCount: result.data.models_count,
      };
    } catch (error) {
      if (error instanceof ModelError) throw error;
      log.warn("Failed to batch create manage tenant models:", error);
      throw new ModelError("Failed to batch create models for tenant", 500);
    }
  },

  // Create/fetch provider models for a specific tenant (admin/manage operation)
  addManageProviderModel: async (params: {
    tenantId: string;
    provider: string;
    type: ModelType;
    apiKey: string;
    baseUrl?: string;
  }): Promise<any[]> => {
    try {
      const response = await fetch(API_ENDPOINTS.model.manageProviderModelCreate, {
        method: "POST",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          tenant_id: params.tenantId,
          provider: params.provider,
          model_type: params.type,
          api_key: params.apiKey,
          ...(params.baseUrl ? { base_url: params.baseUrl } : {}),
        }),
      });

      const result = await response.json();
      if (response.status !== STATUS_CODES.SUCCESS) {
        throw new ModelError(result.detail || result.message || "Failed to create provider models for tenant", response.status);
      }
      return result.data || [];
    } catch (error) {
      if (error instanceof ModelError) throw error;
      log.warn("Failed to create manage provider models:", error);
      throw new ModelError("Failed to create provider models for tenant", 500);
    }
  },

  // Get provider selected modal list for a specific tenant (admin/manage operation)
  getManageProviderSelectedModalList: async (params: {
    tenantId: string;
    provider: string;
    type: ModelType;
  }): Promise<any[]> => {
    try {
      const response = await fetch(API_ENDPOINTS.model.manageProviderModelList, {
        method: "POST",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          tenant_id: params.tenantId,
          provider: params.provider,
          model_type: params.type,
        }),
      });

      const result = await response.json();
      if (response.status !== STATUS_CODES.SUCCESS) {
        throw new ModelError(result.detail || result.message || "Failed to get provider selected list for tenant", response.status);
      }
      return result.data || [];
    } catch (error) {
      if (error instanceof ModelError) throw error;
      log.warn("Failed to get manage provider selected list:", error);
      throw new ModelError("Failed to get provider selected list for tenant", 500);
    }
  },
};

// -------- Provider detection helpers (for UI rendering) --------

/**
 * Detect provider key from the given base URL by substring matching using single hint strings.
 */
export function detectProviderFromUrl(
  apiUrl: string | undefined | null
): ModelProviderKey | null {
  if (!apiUrl) return null;
  const lower = apiUrl.toLowerCase();
  for (const key of MODEL_PROVIDER_KEYS) {
    const hint = PROVIDER_HINTS[key];
    if (lower.includes(hint)) return key;
  }
  return null;
}

/**
 * Get provider icon path from a base URL, falling back to default icon when unknown.
 */
export function getProviderIconByUrl(
  apiUrl: string | undefined | null
): string {
  const key = detectProviderFromUrl(apiUrl);
  return key
    ? PROVIDER_ICON_MAP[key] || DEFAULT_PROVIDER_ICON
    : DEFAULT_PROVIDER_ICON;
}

/**
 * Get icon for official ModelEngine items explicitly.
 */
export function getOfficialProviderIcon(): string {
  return OFFICIAL_PROVIDER_ICON;
}
