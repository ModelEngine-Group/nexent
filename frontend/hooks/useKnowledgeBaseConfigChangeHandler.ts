"use client";

import { useRef, useEffect, useCallback } from "react";

/**
 * Tool types that require knowledge base config change detection
 */
export type ToolKbType =
  | "knowledge_base_search"
  | "dify_search"
  | "datamate_search"
  | "idata_search"
  | "haotian_search"
  | "ragflow_search"
  | "aidp_search";

/**
 * Configuration for Dify tool
 */
export interface DifyConfig {
  serverUrl: string;
  apiKey: string;
}

/**
 * Configuration for RAGFlow tool
 */
export interface RagflowConfig {
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
 * Configuration for AIDP tool
 */
export interface AidpConfig {
  serverUrl: string;
  apiKey: string;
}

/**
 * Options for useKnowledgeBaseConfigChangeHandler hook
 */
export interface UseKnowledgeBaseConfigChangeHandlerOptions {
  toolKbType: ToolKbType | null;
  config: DifyConfig | DatamateConfig | IdataConfig | AidpConfig | RagflowConfig | undefined;
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

  // Track previous RAGFlow config to detect changes
  const prevRagflowConfig = useRef<RagflowConfig>({
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

  const prevAidpConfig = useRef<AidpConfig>({
    serverUrl: "",
    apiKey: "",
  });

  const aidpDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Track if initial load is complete to avoid duplicate API calls
  const isInitialLoadComplete = useRef(false);

  // Generic handler for tools that use serverUrl + apiKey config
  // (dify_search and ragflow_search share the same config shape and change-detection logic)
  useEffect(() => {
    const isRelevantTool = toolKbType === "dify_search" || toolKbType === "ragflow_search";
    if (!isRelevantTool || !config) {
      return;
    }

    const typedConfig = config as { serverUrl: string; apiKey: string };
    const prevRef = toolKbType === "dify_search" ? prevDifyConfig : prevRagflowConfig;

    // Skip initial load — only handle actual config changes
    if (!prevRef.current.serverUrl && !prevRef.current.apiKey) {
      prevRef.current = { ...typedConfig };
      return;
    }

    const hasUrlChanged = typedConfig.serverUrl !== prevRef.current.serverUrl;
    const hasApiKeyChanged = typedConfig.apiKey !== prevRef.current.apiKey;

    if (hasUrlChanged || hasApiKeyChanged) {
      onConfigChange();
      prevRef.current = { ...typedConfig };
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

  useEffect(() => {
    if (toolKbType !== "aidp_search" || !config) {
      return;
    }

    const aidpConfig = config as AidpConfig;

    if (!prevAidpConfig.current.serverUrl && !prevAidpConfig.current.apiKey) {
      prevAidpConfig.current = { ...aidpConfig };
      return;
    }

    const hasServerUrlChanged =
      aidpConfig.serverUrl !== prevAidpConfig.current.serverUrl;
    const hasApiKeyChanged = aidpConfig.apiKey !== prevAidpConfig.current.apiKey;

    if (hasServerUrlChanged || hasApiKeyChanged) {
      // Clear existing debounce timer
      if (aidpDebounceRef.current) {
        clearTimeout(aidpDebounceRef.current);
      }
      // Debounce: wait 500ms after last change before triggering API call
      aidpDebounceRef.current = setTimeout(() => {
        onConfigChange();
        prevAidpConfig.current = { ...aidpConfig };
        isInitialLoadComplete.current = true;
      }, 500);
    }
  }, [toolKbType, config, onConfigChange]);

  // Reset handler - useful when modal closes to reset the tracking state
  const resetTracker = useCallback(() => {
    prevDifyConfig.current = { serverUrl: "", apiKey: "" };
    prevRagflowConfig.current = { serverUrl: "", apiKey: "" };
    prevDatamateServerUrl.current = "";
    prevIdataConfig.current = { serverUrl: "", apiKey: "", userId: "" };
    prevAidpConfig.current = { serverUrl: "", apiKey: "" };
    isInitialLoadComplete.current = false;
    if (aidpDebounceRef.current) {
      clearTimeout(aidpDebounceRef.current);
      aidpDebounceRef.current = null;
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (aidpDebounceRef.current) {
        clearTimeout(aidpDebounceRef.current);
      }
    };
  }, []);

  return {
    resetTracker,
  };
}
