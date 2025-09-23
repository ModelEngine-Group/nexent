'use client';

import { GlobalConfig, AppConfig, ModelConfig } from '../types/modelConfig';
import { APP_CONFIG_KEY, MODEL_CONFIG_KEY, defaultConfig } from '../const/modelConfig';
import log from "@/lib/logger";

class ConfigStoreClass {
  private static instance: ConfigStoreClass | null = null;
  private config: GlobalConfig | null = null;

  private constructor() {
    // Bind all methods to ensure 'this' context is preserved
    this.getConfig = this.getConfig.bind(this);
    this.updateConfig = this.updateConfig.bind(this);
    this.getAppConfig = this.getAppConfig.bind(this);
    this.updateAppConfig = this.updateAppConfig.bind(this);
    this.getModelConfig = this.getModelConfig.bind(this);
    this.updateModelConfig = this.updateModelConfig.bind(this);
    this.clearConfig = this.clearConfig.bind(this);
    this.reloadFromStorage = this.reloadFromStorage.bind(this);
    
    // Initialize config
    this.initializeConfig();
  }

  static getInstance(): ConfigStoreClass {
    if (!ConfigStoreClass.instance) {
      ConfigStoreClass.instance = new ConfigStoreClass();
    }
    return ConfigStoreClass.instance;
  }

  private initializeConfig(): void {
    try {
      this.config = this.loadFromStorage();
    } catch (error) {
      log.error('Failed to initialize config:', error);
      this.config = JSON.parse(JSON.stringify(defaultConfig));
    }
  }

  // Deep merge configuration
  private deepMerge<T>(target: T, source: Partial<T>): T {
    if (!source) return target;
    
    const result = { ...target } as T;
    
    Object.keys(source).forEach(key => {
      const targetValue = (target as any)[key];
      const sourceValue = (source as any)[key];
      
      if (sourceValue && typeof sourceValue === 'object' && !Array.isArray(sourceValue)) {
        (result as any)[key] = this.deepMerge(targetValue, sourceValue);
      } else if (sourceValue !== undefined) {
        (result as any)[key] = sourceValue;
      }
    });
    
    return result;
  }

  // Load configuration from storage
  private loadFromStorage(): GlobalConfig {
    try {
      // Check if we're in browser environment
      if (typeof window === 'undefined') {
        return JSON.parse(JSON.stringify(defaultConfig));
      }

      const storedAppConfig = localStorage.getItem(APP_CONFIG_KEY);
      const storedModelConfig = localStorage.getItem(MODEL_CONFIG_KEY);

      // Start with default configuration
      let mergedConfig: GlobalConfig = JSON.parse(JSON.stringify(defaultConfig));

      // Check for old configuration format and migrate if found
      const oldConfig = localStorage.getItem('config');
      if (oldConfig) {
        try {
          const parsedOldConfig = JSON.parse(oldConfig);
          // Migrate old config to new format
          if (parsedOldConfig.app) localStorage.setItem(APP_CONFIG_KEY, JSON.stringify(parsedOldConfig.app));
          if (parsedOldConfig.models) localStorage.setItem(MODEL_CONFIG_KEY, JSON.stringify(parsedOldConfig.models));
          
          // Remove old config
          localStorage.removeItem('config');
        } catch (error) {
          log.error('Failed to migrate old config:', error);
        }
      }

      // Override with stored configuration
      if (storedAppConfig) {
        try {
          mergedConfig.app = JSON.parse(storedAppConfig);
        } catch (error) {
          log.error('Failed to parse app config:', error);
        }
      }

      if (storedModelConfig) {
        try {
          mergedConfig.models = JSON.parse(storedModelConfig);
        } catch (error) {
          log.error('Failed to parse model config:', error);
        }
      }

      return mergedConfig;
    } catch (error) {
      log.error('Failed to load config from storage:', error);
      return JSON.parse(JSON.stringify(defaultConfig));
    }
  }

  // Save configuration to storage
  private saveToStorage(): void {
    try {
      if (typeof window === 'undefined' || !this.config) return;
      
      localStorage.setItem(APP_CONFIG_KEY, JSON.stringify(this.config.app));
      localStorage.setItem(MODEL_CONFIG_KEY, JSON.stringify(this.config.models));
    } catch (error) {
      log.error('Failed to save config to storage:', error);
    }
  }

  // Ensure configuration is initialized
  private ensureConfig(): void {
    if (!this.config) {
      this.initializeConfig();
    }
  }

  // Get complete configuration
  getConfig(): GlobalConfig {
    this.ensureConfig();
    return this.config!;
  }

  // Update complete configuration
  updateConfig(partial: Partial<GlobalConfig>): void {
    this.ensureConfig();
    this.config = this.deepMerge(this.config!, partial);
    this.saveToStorage();
  }

  // Get application configuration
  getAppConfig(): AppConfig {
    this.ensureConfig();
    return this.config!.app;
  }

  // Update application configuration
  updateAppConfig(partial: Partial<AppConfig>): void {
    this.ensureConfig();
    this.config!.app = this.deepMerge(this.config!.app, partial);
    this.saveToStorage();
  }

  // Get model configuration
  getModelConfig(): ModelConfig {
    this.ensureConfig();
    return this.config!.models;
  }

  // Update model configuration
  updateModelConfig(partial: Partial<ModelConfig>): void {
    this.ensureConfig();
    this.config!.models = this.deepMerge(this.config!.models, partial);
    this.saveToStorage();
  }

  // Clear all configuration
  clearConfig(): void {
    if (typeof window !== 'undefined') {
      localStorage.removeItem(APP_CONFIG_KEY);
      localStorage.removeItem(MODEL_CONFIG_KEY);
    }
    this.config = JSON.parse(JSON.stringify(defaultConfig));
  }

  // New: Backend configuration to frontend localStorage structure
  static transformBackend2Frontend(backendConfig: any): GlobalConfig {
    // Adapt app field
    const app = backendConfig.app
      ? {
          appName: backendConfig.app.name || "",
          appDescription: backendConfig.app.description || "",
          iconType: (backendConfig.app.icon?.type as "preset" | "custom") || "preset",
          customIconUrl: backendConfig.app.icon?.customUrl || null,
          avatarUri: backendConfig.app.icon?.avatarUri || null
        }
      : {
          appName: "",
          appDescription: "",
          iconType: "preset" as "preset" | "custom",
          customIconUrl: null,
          avatarUri: null
        };

    // Adapt models field
    const models = backendConfig.models ? {
      llm: {
        modelName: backendConfig.models.llm?.name || "",
        displayName: backendConfig.models.llm?.displayName || "",
        apiConfig: {
          apiKey: backendConfig.models.llm?.apiConfig?.apiKey || "",
          modelUrl: backendConfig.models.llm?.apiConfig?.modelUrl || ""
        }
      },
      embedding: {
        modelName: backendConfig.models.embedding?.name || "",
        displayName: backendConfig.models.embedding?.displayName || "",
        apiConfig: {
          apiKey: backendConfig.models.embedding?.apiConfig?.apiKey || "",
          modelUrl: backendConfig.models.embedding?.apiConfig?.modelUrl || ""
        },
        dimension: backendConfig.models.embedding?.dimension || 0
      },
      multiEmbedding: {
        modelName: backendConfig.models.multiEmbedding?.name || "",
        displayName: backendConfig.models.multiEmbedding?.displayName || "",
        apiConfig: {
          apiKey: backendConfig.models.multiEmbedding?.apiConfig?.apiKey || "",
          modelUrl: backendConfig.models.multiEmbedding?.apiConfig?.modelUrl || ""
        },
        dimension: backendConfig.models.multiEmbedding?.dimension || 0
      },
      rerank: {
        modelName: backendConfig.models.rerank?.name || "",
        displayName: backendConfig.models.rerank?.displayName || ""
      },
      vlm: {
        modelName: backendConfig.models.vlm?.name || "",
        displayName: backendConfig.models.vlm?.displayName || "",
        apiConfig: {
          apiKey: backendConfig.models.vlm?.apiConfig?.apiKey || "",
          modelUrl: backendConfig.models.vlm?.apiConfig?.modelUrl || ""
        }
      },
      stt: {
        modelName: backendConfig.models.stt?.name || "",
        displayName: backendConfig.models.stt?.displayName || "",
        apiConfig: {
          apiKey: backendConfig.models.stt?.apiConfig?.apiKey || "",
          modelUrl: backendConfig.models.stt?.apiConfig?.modelUrl || ""
        }
      },
      tts: {
        modelName: backendConfig.models.tts?.name || "",
        displayName: backendConfig.models.tts?.displayName || "",
        apiConfig: {
          apiKey: backendConfig.models.tts?.apiConfig?.apiKey || "",
          modelUrl: backendConfig.models.tts?.apiConfig?.modelUrl || ""
        }
      }
    } : undefined;

    return {
      app,
      models,
    } as GlobalConfig;
  }

  // New: Reload configuration from localStorage and trigger configChanged event
  reloadFromStorage(): void {
    this.config = this.loadFromStorage();
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('configChanged', {
        detail: { config: this.config }
      }));
    }
  }
}

// TODO: Why not use just one singleton pattern?
// Export class as ConfigStore
export const ConfigStore = ConfigStoreClass;

// Export singleton
export const configStore = ConfigStoreClass.getInstance(); 