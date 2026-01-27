'use client';

import { useState, useCallback, useEffect } from 'react';

import { GlobalConfig, AppConfig, ModelConfig } from '@/types/modelConfig';
import { ConfigStore } from '@/lib/config';
import { getAvatarUrl } from '@/lib/avatar';

const configStore = ConfigStore.getInstance();

export function useConfig() {
  const [config, setConfig] = useState<GlobalConfig>(configStore.getConfig);

  // Listen to config change event
  useEffect(() => {
    const handleConfigChanged = () => {
      const newConfig = configStore.getConfig();
      setConfig(newConfig);
    };

    window.addEventListener('configChanged', handleConfigChanged);
    return () => {
      window.removeEventListener('configChanged', handleConfigChanged);
    };
  }, []);

  // Update app configuration
  const updateAppConfig = useCallback((partial: Partial<AppConfig>) => {
    configStore.updateAppConfig(partial);
    setConfig(configStore.getConfig());
  }, []);

  // Update model configuration
  const updateModelConfig = useCallback((partial: Partial<ModelConfig>) => {
    configStore.updateModelConfig(partial);
    setConfig(configStore.getConfig());
  }, []);

  // Get complete configuration
  const getConfig = useCallback(() => {
    return configStore.getConfig();
  }, []);

  // Update complete configuration
  const updateConfig = useCallback((newConfig: GlobalConfig) => {
    configStore.updateConfig(newConfig);
    setConfig(configStore.getConfig());
  }, []);

  // Clear configuration
  const clearConfig = useCallback(() => {
    configStore.clearConfig();
    setConfig(configStore.getConfig());
  }, []);

  // Get avatar URL
  const getAppAvatarUrl = useCallback((size?: number) => {
    return getAvatarUrl(config.app, size);
  }, [config.app]);

  return {
    config,
    updateAppConfig,
    updateModelConfig,
    getConfig,
    updateConfig,
    clearConfig,
    // Convenient access
    appConfig: config.app,
    modelConfig: config.models,
    // Avatar related functionality
    getAppAvatarUrl
  };
} 