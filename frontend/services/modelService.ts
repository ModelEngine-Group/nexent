"use client";

import { API_ENDPOINTS } from "./api";

import {
  ModelOption,
  ModelType,
  ModelConnectStatus,
  ModelValidationResponse,
  ModelSource,
} from "@/types/modelConfig";

import { getAuthHeaders } from '@/lib/auth'
import {STATUS_CODES} from "@/const/auth";
import { MODEL_TYPES, MODEL_SOURCES } from '@/const/modelConfig';
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
  // Get official model list
  getOfficialModels: async (): Promise<ModelOption[]> => {
    try {
      const response = await fetch(API_ENDPOINTS.model.officialModelList, {
        headers: getAuthHeaders(),
      });
      const result = await response.json();
      
      if (response.status === STATUS_CODES.SUCCESS && result.data) {
        const modelOptions: ModelOption[] = [];
        const typeMap: Record<string, ModelType> = {
          embed: MODEL_TYPES.EMBEDDING,
          chat: MODEL_TYPES.LLM,
          asr: MODEL_TYPES.STT,
          tts: MODEL_TYPES.TTS,
          rerank: MODEL_TYPES.RERANK,
          vlm: MODEL_TYPES.VLM,
        };

        for (const model of result.data) {
          if (typeMap[model.type]) {
            modelOptions.push({
              id: model.id,
              name: model.id,
              type: typeMap[model.type],
              maxTokens: 0,
              source: MODEL_SOURCES.OPENAI_API_COMPATIBLE,
              apiKey: model.api_key,
              apiUrl: model.base_url,
              displayName: model.id,
            });
          }
        }

        return modelOptions;
      }
      // If API call was not successful, return empty array
      return [];
    } catch (error) {
      // In case of any error, return empty array
      log.warn("Failed to load official models:", error);
      return [];
    }
  },

  // Get custom model list
  getCustomModels: async (): Promise<ModelOption[]> => {
    try {
      const response = await fetch(API_ENDPOINTS.model.customModelList, {
        headers: getAuthHeaders(),
      });
      const result = await response.json();

      if (response.status === 200 && result.data) {
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
        }));
      }
      // If API call was not successful, return empty array
      log.warn(
        "Failed to load custom models:",
        result.message || "Unknown error"
      );
      return [];
    } catch (error) {
      // In case of any error, return empty array
      log.warn("Failed to load custom models:", error);
      return [];
    }
  },

  // Add custom model
  addCustomModel: async (model: {
    name: string;
    type: ModelType;
    url: string;
    apiKey: string;
    maxTokens: number;
    displayName?: string;
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
        }),
      });

      const result = await response.json();

      if (response.status !== 200) {
        throw new ModelError(
          result.message || "添加自定义模型失败",
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
          }),
        }
      );

      const result = await response.json();

      if (response.status !== 200) {
        throw new ModelError(
          result.message || "添加自定义模型失败",
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
          result.message || "添加自定义模型失败",
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
          }),
        }
      );
      log.log("getProviderSelectedModalList response", response);
      const result = await response.json();
      log.log("getProviderSelectedModalList result", result);
      if (response.status !== 200) {
        throw new ModelError(
          result.message || "获取模型列表失败",
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

  updateSingleModel: async (model: {
    model_id: string;
    displayName: string;
    url: string;
    apiKey: string;
    maxTokens?: number;
    source?: ModelSource;
  }): Promise<void> => {
    try {
      const response = await fetch(API_ENDPOINTS.model.updateSingleModel, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          model_id: model.model_id,
          display_name: model.displayName,
          base_url: model.url,
          api_key: model.apiKey,
          ...(model.maxTokens !== undefined
            ? { max_tokens: model.maxTokens }
            : {}),
          model_factory: model.source || "OpenAI-API-Compatible",
        }),
      });
      const result = await response.json();
      if (response.status !== 200) {
        throw new ModelError(
          result.message || "Failed to update the custom model",
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
    }[]
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
          }))
        ),
      });
      const result = await response.json();
      if (response.status !== 200) {
        throw new ModelError(
          result.message || "Failed to update the custom model",
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
  deleteCustomModel: async (displayName: string): Promise<void> => {
    try {
      const response = await fetch(
        API_ENDPOINTS.model.customModelDelete(displayName),
        {
          method: "POST",
          headers: getAuthHeaders(),
        }
      );
      const result = await response.json();
      if (response.status !== 200) {
        throw new ModelError(
          result.message || "删除自定义模型失败",
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
        };
      }

      return {
        connectivity: false,
        model_name: result.data?.model_name || "UNKNOWN_MODEL",
      };
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        log.warn("Model configuration connectivity verification cancelled");
        throw error;
      }
      log.error(
        "Model configuration connectivity verification failed:",
        error
      );
      return {
        connectivity: false,
        model_name: "UNKNOWN_MODEL",
      };
    }
  },
};
