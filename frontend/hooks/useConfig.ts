"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { configService } from "@/services/configService";
import {
  GlobalConfig,
  AppConfig,
  ModelConfig,
  SingleModelConfig,
} from "@/types/modelConfig";
import { ICON_TYPES } from "@/const/modelConfig";
import { getAvatarUrl } from "@/lib/avatar";
import log from "@/lib/logger";

const APP_CONFIG_KEY = "app";
const MODEL_CONFIG_KEY = "model";

/**
 * Query key for config data
 */
export const CONFIG_QUERY_KEY = ["config"];

const defaultConfig: GlobalConfig = {
  app: {
    appName: "",
    appDescription: "",
    iconType: ICON_TYPES.PRESET,
    iconKey: "search",
    customIconUrl: "",
    avatarUri: "",
    modelEngineEnabled: false,
    datamateUrl: "",
  },
  models: {
    llm: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: "",
      },
    },
    embedding: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: "",
      },
      dimension: 0,
    },
    multiEmbedding: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: "",
      },
      dimension: 0,
    },
    rerank: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: "",
      },
    },
    vlm: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: "",
      },
    },
    stt: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: "",
      },
    },
    tts: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: "",
      },
    },
  },
};

function transformModelEntry(
  raw: Record<string, any> | undefined,
  withDimension = false
): SingleModelConfig {
  return {
    modelName: raw?.name || "",
    displayName: raw?.displayName || "",
    apiConfig: {
      apiKey: raw?.apiConfig?.apiKey || "",
      modelUrl: raw?.apiConfig?.modelUrl || "",
    },
    ...(withDimension ? { dimension: raw?.dimension || 0 } : {}),
  };
}

/**
 * Transform backend config format to frontend format
 */
function transformBackendToFrontend(backendConfig: any): GlobalConfig {
  // Get iconKey from backend - if not available, use default "search"
  const iconKey = backendConfig.app?.icon?.iconKey || "search";

  const app: AppConfig = backendConfig.app
    ? {
        appName: backendConfig.app.name || "",
        appDescription: backendConfig.app.description || "",
        iconType:
          (backendConfig.app.icon?.type as "preset" | "custom") || "preset",
        iconKey: iconKey,
        customIconUrl: backendConfig.app.icon?.customUrl || null,
        avatarUri: backendConfig.app.icon?.avatarUri || null,
        modelEngineEnabled: backendConfig.app.modelEngineEnabled ?? false,
        datamateUrl: backendConfig.app.datamateUrl || null,
      }
    : defaultConfig.app;

  const models: ModelConfig = backendConfig.models
    ? {
        llm: transformModelEntry(backendConfig.models.llm),
        embedding: transformModelEntry(backendConfig.models.embedding, true),
        multiEmbedding: transformModelEntry(
          backendConfig.models.multiEmbedding,
          true
        ),
        rerank: transformModelEntry(backendConfig.models.rerank),
        vlm: transformModelEntry(backendConfig.models.vlm),
        stt: transformModelEntry(backendConfig.models.stt),
        tts: transformModelEntry(backendConfig.models.tts),
      }
    : defaultConfig.models;

  return { app, models };
}

/**
 * Load config from localStorage
 */
function loadConfigFromStorage(): GlobalConfig | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const storedAppConfig = localStorage.getItem(APP_CONFIG_KEY);
    const storedModelConfig = localStorage.getItem(MODEL_CONFIG_KEY);

    let mergedConfig: GlobalConfig = JSON.parse(
      JSON.stringify(defaultConfig)
    );

    if (storedAppConfig) {
      try {
        mergedConfig.app = JSON.parse(storedAppConfig);
      } catch (error) {
        log.error("Failed to parse app config:", error);
      }
    }

    if (storedModelConfig) {
      try {
        mergedConfig.models = JSON.parse(storedModelConfig);
      } catch (error) {
        log.error("Failed to parse model config:", error);
      }
    }

    return mergedConfig;
  } catch (error) {
    log.error("Failed to load config from storage:", error);
    return null;
  }
}

/**
 * Save config to localStorage
 */
function saveConfigToStorage(config: GlobalConfig): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    if (config.app) {
      localStorage.setItem(APP_CONFIG_KEY, JSON.stringify(config.app));
    }
    if (config.models) {
      localStorage.setItem(MODEL_CONFIG_KEY, JSON.stringify(config.models));
    }
  } catch (error) {
    log.error("Failed to save config to storage:", error);
  }
}

/**
 * Deep merge configuration
 */
function deepMerge<T>(target: T, source: Partial<T>): T {
  if (!source) return target;
  if (!target) return source as T;

  const result = { ...target } as T;

  Object.keys(source).forEach((key) => {
    const targetValue = (target as any)[key];
    const sourceValue = (source as any)[key];

    if (
      sourceValue &&
      typeof sourceValue === "object" &&
      !Array.isArray(sourceValue)
    ) {
      if (targetValue !== undefined && targetValue !== null) {
        (result as any)[key] = deepMerge(targetValue, sourceValue);
      } else {
        (result as any)[key] = sourceValue;
      }
    } else if (sourceValue !== undefined) {
      (result as any)[key] = sourceValue;
    }
  });

  return result;
}

/**
 * Main hook to fetch and manage configuration
 * Handles React Query caching, localStorage persistence, and format transformation
 */
export function useConfig() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: CONFIG_QUERY_KEY,
    queryFn: async () => {
      const backendConfig = await configService.fetchConfig();
      const frontendConfig = transformBackendToFrontend(backendConfig);
      saveConfigToStorage(frontendConfig);
      return frontendConfig;
    },
    initialData: loadConfigFromStorage() ?? undefined,
    initialDataUpdatedAt: 0,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    retry: 2,
    refetchOnWindowFocus: false,
  });

  const config: GlobalConfig = (query.data as GlobalConfig | undefined) ?? defaultConfig;

  // Whether config has selected a VLM model
  const isVlmAvailable = !!(config?.models?.vlm?.modelName || config?.models?.vlm?.displayName);

  // Whether config has selected an Embedding model
  const isEmbeddingAvailable = !!(config?.models?.embedding?.modelName || config?.models?.embedding?.displayName);

  // Whether config has selected a Multi-Embedding model
  const isMultiEmbeddingAvailable = !!(config?.models?.multiEmbedding?.modelName || config?.models?.multiEmbedding?.displayName);

  // Default LLM model name from config (modelName or displayName)
  const defaultLlmModelName = config?.models?.llm?.modelName || config?.models?.llm?.displayName || "";

  const updateAppConfig = useCallback(
    (partial: Partial<AppConfig>) => {
      if (!config) return;
      const updated: GlobalConfig = {
        ...config,
        app: deepMerge(config.app, partial),
      };
      queryClient.setQueryData(CONFIG_QUERY_KEY, updated);
      saveConfigToStorage(updated);
    },
    [config, queryClient]
  );

  const updateModelConfig = useCallback(
    (partial: Partial<ModelConfig>) => {
      if (!config) return;
      const updated: GlobalConfig = {
        ...config,
        models: deepMerge(config.models, partial),
      };
      queryClient.setQueryData(CONFIG_QUERY_KEY, updated);
      saveConfigToStorage(updated);
    },
    [config, queryClient]
  );

  const updateConfig = useCallback(
    (newConfig: GlobalConfig | Partial<GlobalConfig>) => {
      if (!config) return;
      const updated: GlobalConfig = deepMerge(config, newConfig);
      queryClient.setQueryData(CONFIG_QUERY_KEY, updated);
      saveConfigToStorage(updated);
    },
    [config, queryClient]
  );

  const getAppAvatarUrl = useCallback(
    (size?: number) => {
      if (!config?.app) return "";
      return getAvatarUrl(config.app, size);
    },
    [config?.app]
  );

  /**
   * Save config to backend and invalidate cache.
   * When called with no argument, saves the current cached config.
   * When called with a GlobalConfig, saves that specific config.
   */
  const saveConfig = useCallback(
    async (configToSave?: GlobalConfig): Promise<boolean> => {
      const target = configToSave ?? (queryClient.getQueryData(CONFIG_QUERY_KEY) as GlobalConfig | undefined) ?? config;
      if (!target) return false;
      try {
        await configService.saveConfig(target);
        await queryClient.invalidateQueries({ queryKey: CONFIG_QUERY_KEY });
        return true;
      } catch (error) {
        log.error("Failed to save config:", error);
        return false;
      }
    },
    [config, queryClient]
  );

  const invalidateConfig = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: CONFIG_QUERY_KEY });
  }, [queryClient]);

  return {
    ...query,
    config,
    appConfig: config?.app,
    modelConfig: config?.models,
    isVlmAvailable,
    isEmbeddingAvailable,
    isMultiEmbeddingAvailable,
    defaultLlmModelName,
    updateAppConfig,
    updateModelConfig,
    updateConfig,
    getAppAvatarUrl,
    saveConfig,
    invalidateConfig,
  };
}
