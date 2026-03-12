"use client";

import { useRef, useEffect, useCallback } from "react";

/**
 * Tool types that require knowledge base config change detection
 */
export type ToolKbType =
  | "knowledge_base_search"
  | "dify_search"
  | "datamate_search"
  | "idata_search";

/**
 * Configuration for Dify tool
 */
export interface DifyConfig {
  serverUrl: string;
  apiKey: string;
}

/**
 * Configuration for DataMate tool
 */
export interface DatamateConfig {
  serverUrl: string;
}

/**
 * Configuration for iData tool
 */
export interface IdataConfig {
  serverUrl: string;
  apiKey: string;
  userId: string;
}

/**
 * Options for useKnowledgeBaseConfigChangeHandler hook
 */
export interface UseKnowledgeBaseConfigChangeHandlerOptions {
  toolKbType: ToolKbType | null;
  config: DifyConfig | DatamateConfig | IdataConfig | undefined;
  onConfigChange: () => void;
}

/**
 * Hook for detecting knowledge base config changes and triggering callbacks
 * Handles both Dify (serverUrl + apiKey) and DataMate (serverUrl only) config changes
 * When config changes, it triggers onConfigChange to clear selection and refetch
 */
export function useKnowledgeBaseConfigChangeHandler({
  toolKbType,
  config,
  onConfigChange,
}: UseKnowledgeBaseConfigChangeHandlerOptions) {
  // Track previous Dify config to detect changes
  const prevDifyConfig = useRef<DifyConfig>({
    serverUrl: "",
    apiKey: "",
  });

  // Track previous DataMate URL to detect changes
  const prevDatamateServerUrl = useRef<string>("");

  // Track previous iData config to detect changes
  const prevIdataConfig = useRef<IdataConfig>({
    serverUrl: "",
    apiKey: "",
    userId: "",
  });

  // Track if initial load is complete to avoid duplicate API calls
  const isInitialLoadComplete = useRef(false);

  // Handle Dify config change
  useEffect(() => {
    if (toolKbType !== "dify_search" || !config) {
      return;
    }

    const difyConfig = config as DifyConfig;

    // Skip initial load - only handle actual config changes
    if (!prevDifyConfig.current.serverUrl && !prevDifyConfig.current.apiKey) {
      prevDifyConfig.current = { ...difyConfig };
      return;
    }

    const hasUrlChanged = difyConfig.serverUrl !== prevDifyConfig.current.serverUrl;
    const hasApiKeyChanged = difyConfig.apiKey !== prevDifyConfig.current.apiKey;

    // If URL or API key has changed, trigger callback
    if (hasUrlChanged || hasApiKeyChanged) {
      // Only clear and refetch if both values are not empty
      if (difyConfig.serverUrl && difyConfig.apiKey) {
        onConfigChange();
      } else {
        // Clear knowledge base list when URL or API key is cleared
        onConfigChange();
      }

      // Update previous config
      prevDifyConfig.current = { ...difyConfig };
      isInitialLoadComplete.current = true;
    }
  }, [toolKbType, config, onConfigChange]);

  // Handle DataMate config change
  useEffect(() => {
    if (toolKbType !== "datamate_search" || !config) {
      return;
    }

    const datamateConfig = config as DatamateConfig;

    // Skip initial load - only handle actual URL changes
    if (!prevDatamateServerUrl.current) {
      prevDatamateServerUrl.current = datamateConfig.serverUrl;
      return;
    }

    const hasUrlChanged = datamateConfig.serverUrl !== prevDatamateServerUrl.current;

    // If URL has changed, trigger callback
    if (hasUrlChanged) {
      // Clear previous knowledge base selection and refetch
      onConfigChange();

      // Update previous URL
      prevDatamateServerUrl.current = datamateConfig.serverUrl;
      isInitialLoadComplete.current = true;
    }
  }, [toolKbType, config, onConfigChange]);

  // Handle iData config change
  useEffect(() => {
    if (toolKbType !== "idata_search" || !config) {
      return;
    }

    const idataConfig = config as IdataConfig;

    // Skip initial load - only handle actual config changes
    if (
      !prevIdataConfig.current.serverUrl &&
      !prevIdataConfig.current.apiKey &&
      !prevIdataConfig.current.userId
    ) {
      prevIdataConfig.current = { ...idataConfig };
      return;
    }

    const hasUrlChanged =
      idataConfig.serverUrl !== prevIdataConfig.current.serverUrl;
    const hasApiKeyChanged =
      idataConfig.apiKey !== prevIdataConfig.current.apiKey;
    const hasUserIdChanged =
      idataConfig.userId !== prevIdataConfig.current.userId;

    // If URL, API key, or user ID has changed, trigger callback
    if (hasUrlChanged || hasApiKeyChanged || hasUserIdChanged) {
      // Clear knowledge base list when config is cleared
      onConfigChange();

      // Update previous config
      prevIdataConfig.current = { ...idataConfig };
      isInitialLoadComplete.current = true;
    }
  }, [toolKbType, config, onConfigChange]);

  // Reset handler - useful when modal closes to reset the tracking state
  const resetTracker = useCallback(() => {
    prevDifyConfig.current = { serverUrl: "", apiKey: "" };
    prevDatamateServerUrl.current = "";
    prevIdataConfig.current = { serverUrl: "", apiKey: "", userId: "" };
    isInitialLoadComplete.current = false;
  }, []);

  return {
    resetTracker,
  };
}
