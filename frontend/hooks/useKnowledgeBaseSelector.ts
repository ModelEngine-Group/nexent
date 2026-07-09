"use client";

/**
 * @fileoverview Hybrid service imports — partially migrated to `unifiedKBService`.
 *
 * New adapter-related logic uses `unifiedKBService`. Legacy selection-state
 * management (`shouldLoadSelected`, `selectedIds`, per-item loading) still
 * calls `knowledgeBaseService` because the unified API has no equivalent
 * selection-state concept. This is intentional, not a migration gap.
 */
import { useState, useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import knowledgeBaseService from "@/services/knowledgeBaseService";
import unifiedKBService from "@/services/unifiedKBService";
import { KnowledgeBase } from "@/types/knowledgeBase";
import { UnifiedAdapter, UnifiedKnowledgeBase } from "@/types/unifiedKB";
import log from "@/lib/logger";
import { showErrorToUser } from "@/const/errorMessageI18n";

/**
 * Query key factory for knowledge bases
 */
export const knowledgeBaseKeys = {
  all: ["knowledgeBases"] as const,
  lists: () => [...knowledgeBaseKeys.all, "list"] as const,
  list: (toolType: string, difyServerUrl?: string) =>
    difyServerUrl
      ? ([...knowledgeBaseKeys.lists(), toolType, difyServerUrl] as const)
      : ([...knowledgeBaseKeys.lists(), toolType] as const),
};

/**
 * Hook for fetching knowledge bases based on tool type with React Query caching
 * Uses cache to avoid repeated API calls on the same page
 */
export function useKnowledgeBasesForToolConfig(
  toolType:
    | "knowledge_base_search"
    | "dify_search"
    | "datamate_search"
    | "idata_search"
    | "haotian_search"
    | "aidp_search"
    | "external_kb_search"
    | null = null,
  config?: {
    serverUrl?: string;
    apiKey?: string;
    userId?: string;
    knowledgeSpaceId?: string;
  }
) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  // Support both difyConfig and datamateConfig naming conventions
  const difyConfig = config;
  const datamateConfig = config;
  const idataConfig = config;
  const aidpConfig = config;

  const query = useQuery({
    queryKey: knowledgeBaseKeys.list(
      toolType || "default",
      difyConfig?.serverUrl || ""
    ),
    queryFn: async () => {
      let kbs: KnowledgeBase[] = [];

      // Fetch knowledge bases based on tool type
      if (toolType === "datamate_search") {
        // Sync DataMate knowledge bases with optional URL from config
        const syncResult =
          await knowledgeBaseService.syncDataMateAndCreateRecords(
            datamateConfig?.serverUrl
          );
        if (syncResult.indices_info) {
          kbs = syncResult.indices_info.map((indexInfo: any) => {
            const stats = indexInfo.stats?.base_info || {};
            const kbId = indexInfo.name;
            const kbName = indexInfo.display_name || indexInfo.name;

            return {
              id: kbId,
              name: kbName,
              display_name: indexInfo.display_name || indexInfo.name,
              description: "DataMate knowledge base",
              documentCount: stats.doc_count || 0,
              chunkCount: stats.chunk_count || 0,
              createdAt: stats.creation_date || null,
              updatedAt: stats.update_date || stats.creation_date || null,
              embeddingModel: stats.embedding_model || "unknown",
              knowledge_sources: indexInfo.knowledge_sources || "datamate",
              ingroup_permission: indexInfo.ingroup_permission || "",
              group_ids: indexInfo.group_ids || [],
              store_size: stats.store_size || "",
              process_source: stats.process_source || "",
              avatar: "",
              chunkNum: 0,
              language: "",
              nickname: "",
              parserId: "",
              permission: indexInfo.permission || "",
              tokenNum: 0,
              source: "datamate",
              tenant_id: indexInfo.tenant_id,
            };
          });
        }
      } else if (toolType === "dify_search") {
        // For Dify, fetch knowledge bases using provided config
        if (difyConfig?.serverUrl && difyConfig?.apiKey) {
          // Don't catch error here - let it propagate to React Query so caller can handle it
          kbs = await knowledgeBaseService.getDifyKnowledgeBases(
            difyConfig.serverUrl,
            difyConfig.apiKey
          );
          log.info("Dify knowledge bases fetched successfully:", kbs.length);
        } else {
          // No Dify config provided, return empty
          kbs = [];
        }
      } else if (toolType === "idata_search") {
        // For iData, fetch knowledge bases using provided config
        if (
          idataConfig?.serverUrl &&
          idataConfig?.apiKey &&
          idataConfig?.userId &&
          idataConfig?.knowledgeSpaceId
        ) {
          try {
            kbs = await knowledgeBaseService.getIdataKnowledgeBases(
              idataConfig.serverUrl,
              idataConfig.apiKey,
              idataConfig.userId,
              idataConfig.knowledgeSpaceId
            );
          } catch (error: any) {
            log.error("Failed to fetch iData knowledge bases:", error);
            // Show i18n error message to user
            showErrorToUser(error, t);
            kbs = [];
          }
        } else {
          // No iData config provided, return empty
          kbs = [];
        }
      } else if (toolType === "aidp_search") {
        if (aidpConfig?.serverUrl && aidpConfig?.apiKey) {
          try {
            const result = await knowledgeBaseService.getAidpKnowledgeBases(
              aidpConfig.serverUrl,
              aidpConfig.apiKey,
              1,
              100
            );
            kbs = knowledgeBaseService.mapAidpKnowledgeBasesToKnowledgeBases(
              result.value || []
            );
          } catch (error: any) {
            log.error("Failed to fetch AIDP knowledge bases:", error);
            showErrorToUser(error, t);
            kbs = [];
          }
        } else {
          kbs = [];
        }
      } else {
        // Default: knowledge_base_search or unknown - only get Nexent knowledge bases
        const result = await knowledgeBaseService.getKnowledgeBasesInfo(false, false);
        kbs = result.knowledgeBases;
      }

      // Sort by updatedAt descending
      return kbs.sort((a, b) => {
        const dateA = a.updatedAt ? new Date(a.updatedAt).getTime() : 0;
        const dateB = b.updatedAt ? new Date(b.updatedAt).getTime() : 0;
        return dateB - dateA;
      });
    },
    enabled: !!toolType,
    staleTime: 30_000, // Cache for 30 seconds to reduce API calls
    gcTime: 5 * 60_000, // Keep in cache for 5 minutes
    refetchOnMount: false, // Only refetch if data is stale
    refetchOnWindowFocus: false, // Don't refetch on window focus
    retry: 0, // Don't retry on failure - show error immediately
  });

  // Provide a method to clear knowledge bases cache (useful when sync fails)
  const clearKnowledgeBases = useCallback(() => {
    queryClient.setQueryData(
      knowledgeBaseKeys.list(toolType || "default", difyConfig?.serverUrl || ""),
      []
    );
  }, [queryClient, toolType, difyConfig?.serverUrl]);

  return { ...query, clearKnowledgeBases };
}

/**
 * Prefetch knowledge bases for a specific tool type
 * Call this when the user navigates to the agent config page
 */
export function usePrefetchKnowledgeBases() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const prefetchKnowledgeBases = useCallback(
    async (
      toolType:
        | "knowledge_base_search"
        | "dify_search"
        | "datamate_search"
        | "idata_search"
        | "haotian_search"
        | "aidp_search"
        | "external_kb_search"
        | null,
      difyConfig?: {
        serverUrl?: string;
        apiKey?: string;
        userId?: string;
        knowledgeSpaceId?: string;
      }
    ) => {
      if (!toolType) return;

      await queryClient.prefetchQuery({
        queryKey: knowledgeBaseKeys.list(
          toolType,
          difyConfig?.serverUrl || ""
        ),
        queryFn: async () => {
          let kbs: KnowledgeBase[] = [];

          if (toolType === "datamate_search") {
            const syncResult =
              await knowledgeBaseService.syncDataMateAndCreateRecords();
            if (syncResult.indices_info) {
              kbs = syncResult.indices_info.map((indexInfo: any) => {
                const stats = indexInfo.stats?.base_info || {};
                return {
                  id: indexInfo.name,
                  name: indexInfo.display_name || indexInfo.name,
                  display_name: indexInfo.display_name || indexInfo.name,
                  description: "DataMate knowledge base",
                  documentCount: stats.doc_count || 0,
                  chunkCount: stats.chunk_count || 0,
                  createdAt: stats.creation_date || null,
                  updatedAt: stats.update_date || stats.creation_date || null,
                  embeddingModel: stats.embedding_model || "unknown",
                  knowledge_sources: indexInfo.knowledge_sources || "datamate",
                  ingroup_permission: indexInfo.ingroup_permission || "",
                  group_ids: indexInfo.group_ids || [],
                  store_size: stats.store_size || "",
                  process_source: stats.process_source || "",
                  avatar: "",
                  chunkNum: 0,
                  language: "",
                  nickname: "",
                  parserId: "",
                  permission: indexInfo.permission || "",
                  tokenNum: 0,
                  source: "datamate",
                  tenant_id: indexInfo.tenant_id,
                };
              });
            }
          } else if (toolType === "dify_search") {
            if (difyConfig?.serverUrl && difyConfig?.apiKey) {
              try {
                kbs = await knowledgeBaseService.getDifyKnowledgeBases(
                  difyConfig.serverUrl,
                  difyConfig.apiKey
                );
              } catch (error: any) {
                log.error("Failed to prefetch Dify knowledge bases:", error);
                // Show i18n error message to user
                showErrorToUser(error, t);
                kbs = [];
              }
            } else {
              kbs = [];
            }
          } else if (toolType === "idata_search") {
            if (
              difyConfig?.serverUrl &&
              difyConfig?.apiKey &&
              difyConfig?.userId &&
              difyConfig?.knowledgeSpaceId
            ) {
              try {
                kbs = await knowledgeBaseService.getIdataKnowledgeBases(
                  difyConfig.serverUrl,
                  difyConfig.apiKey,
                  difyConfig.userId,
                  difyConfig.knowledgeSpaceId
                );
              } catch (error: any) {
                log.error("Failed to prefetch iData knowledge bases:", error);
                // Show i18n error message to user
                showErrorToUser(error, t);
                kbs = [];
              }
            } else {
              kbs = [];
            }
          } else if (toolType === "aidp_search") {
            if (difyConfig?.serverUrl && difyConfig?.apiKey) {
              try {
                const result = await knowledgeBaseService.getAidpKnowledgeBases(
                  difyConfig.serverUrl,
                  difyConfig.apiKey,
                  1,
                  100
                );
                kbs = knowledgeBaseService.mapAidpKnowledgeBasesToKnowledgeBases(
                  result.value || []
                );
              } catch (error: any) {
                log.error("Failed to prefetch AIDP knowledge bases:", error);
                showErrorToUser(error, t);
                kbs = [];
              }
            } else {
              kbs = [];
            }
          } else {
            const result = await knowledgeBaseService.getKnowledgeBasesInfo(false, false);
            kbs = result.knowledgeBases;
          }

          return kbs.sort((a, b) => {
            const dateA = a.updatedAt ? new Date(a.updatedAt).getTime() : 0;
            const dateB = b.updatedAt ? new Date(b.updatedAt).getTime() : 0;
            return dateB - dateA;
          });
        },
        staleTime: 30_000,
      });
    },
    [queryClient]
  );

  return { prefetchKnowledgeBases };
}

/**
 * Hook for syncing knowledge bases by tool type
 */
export function useSyncKnowledgeBases() {
  const { t } = useTranslation();
  const [isSyncing, setIsSyncing] = useState<string | null>(null);

  const syncKnowledgeBases = useCallback(
    async (
      toolType: string,
      config?: {
        serverUrl?: string;
        apiKey?: string;
        userId?: string;
        knowledgeSpaceId?: string;
      }
    ): Promise<void> => {
      setIsSyncing(toolType);
      try {
        switch (toolType) {
          case "knowledge_base_search":
            // Sync only Nexent knowledge bases (exclude DataMate)
            await knowledgeBaseService.getKnowledgeBasesInfo(false, false);
            break;
          case "datamate_search":
            // Sync only DataMate knowledge bases with optional URL from config
            await knowledgeBaseService.syncDataMateAndCreateRecords(
              config?.serverUrl
            );
            break;
          case "dify_search":
            // Dify sync requires API credentials
            if (config?.serverUrl && config?.apiKey) {
              await knowledgeBaseService.getDifyKnowledgeBases(
                config.serverUrl,
                config.apiKey
              );
            }
            break;
          case "idata_search":
            // iData sync requires API credentials and knowledge space ID
            if (
              config?.serverUrl &&
              config?.apiKey &&
              config?.userId &&
              config?.knowledgeSpaceId
            ) {
              await knowledgeBaseService.getIdataKnowledgeBases(
                config.serverUrl,
                config.apiKey,
                config.userId,
                config.knowledgeSpaceId
              );
            }
            break;
          case "aidp_search":
            // AIDP sync requires server URL and API key
            if (config?.serverUrl && config?.apiKey) {
              await knowledgeBaseService.getAidpKnowledgeBases(
                config.serverUrl,
                config.apiKey,
                1,
                100
              );
            }
            break;
          default:
            // Default sync behavior - sync Nexent only
            await knowledgeBaseService.getKnowledgeBasesInfo(false, false);
        }
      } catch (error: any) {
        log.error("Failed to sync knowledge bases:", error);
        // Show i18n error message to user
        showErrorToUser(error, t);
      } finally {
        setIsSyncing(null);
      }
    },
    []
  );

  return {
    syncKnowledgeBases,
    isSyncing,
  };
}

/**
 * Hook for managing knowledge base selection in tool configuration
 */
export function useKnowledgeBaseSelection(initialSelectedIds: string[] = []) {
  const [selectedIds, setSelectedIds] = useState<string[]>(initialSelectedIds);
  const [selectedKnowledgeBases, setSelectedKnowledgeBases] = useState<
    KnowledgeBase[]
  >([]);

  // Update selected knowledge bases when IDs change
  const updateSelectedKnowledgeBases = useCallback((kbs: KnowledgeBase[]) => {
    setSelectedKnowledgeBases(kbs);
  }, []);

  // Select a knowledge base by ID
  const selectKnowledgeBase = useCallback((id: string) => {
    setSelectedIds((prev) => {
      if (prev.includes(id)) {
        return prev;
      }
      return [...prev, id];
    });
  }, []);

  // Deselect a knowledge base by ID
  const deselectKnowledgeBase = useCallback((id: string) => {
    setSelectedIds((prev) => prev.filter((itemId) => itemId !== id));
  }, []);

  // Toggle selection of a knowledge base
  const toggleKnowledgeBase = useCallback((id: string) => {
    setSelectedIds((prev) => {
      if (prev.includes(id)) {
        return prev.filter((itemId) => itemId !== id);
      }
      return [...prev, id];
    });
  }, []);

  // Clear all selections
  const clearSelection = useCallback(() => {
    setSelectedIds([]);
    setSelectedKnowledgeBases([]);
  }, []);

  // Set selected IDs (e.g., from initial value)
  const setSelection = useCallback((ids: string[]) => {
    setSelectedIds(ids);
  }, []);

  return {
    selectedIds,
    selectedKnowledgeBases,
    setSelectedIds: setSelection,
    updateSelectedKnowledgeBases,
    selectKnowledgeBase,
    deselectKnowledgeBase,
    toggleKnowledgeBase,
    clearSelection,
    hasSelection: selectedIds.length > 0,
    selectionCount: selectedIds.length,
  };
}

// ============================================================================
// P3-A hooks for cross-adapter (ExternalKnowledgeSearchTool) KB selection
// ============================================================================

/**
 * Query key factory for unified KB adapter listing.
 */
export const unifiedKbKeys = {
  all: ["unifiedKb"] as const,
  adapters: () => [...unifiedKbKeys.all, "adapters"] as const,
  kbsForAdapter: (adapterId: number) =>
    [...unifiedKbKeys.all, "adapter", adapterId] as const,
};

/**
 * Hook for fetching the list of enabled KB adapters via unifiedKBService.
 * Returns only adapters with `enabled === true`.
 *
 * Used by ExternalKbSearchSelectorModal to let the user pick which adapters
 * to search across.
 */
export function useKbAdapters() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: unifiedKbKeys.adapters(),
    queryFn: async (): Promise<UnifiedAdapter[]> => {
      try {
        const response = await unifiedKBService.listAdapters(true);
        const adapters = Array.isArray(response.list) ? response.list : [];
        return adapters.filter((a) => a.enabled === true);
      } catch (error: any) {
        log.error("Failed to fetch KB adapters:", error);
        return [];
      }
    },
    staleTime: 60_000,
    gcTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: unifiedKbKeys.adapters() });
  }, [queryClient]);

  return { ...query, invalidate };
}

/**
 * Hook for fetching knowledge bases for a specific adapter via unifiedKBService.
 *
 * When `adapterId` is null/undefined, the query is disabled and returns an empty list.
 * Maps UnifiedKnowledgeBase → legacy-shape KnowledgeBase[] so that the UI
 * components can render KB chips the same way they do for the legacy selectors.
 *
 * Each returned KnowledgeBase carries:
 *   - `adapter_id` and `adapter_name` (enriched from the adapter record)
 *   - `source` === adapter.platform (e.g. "local", "dify", "aidp")
 *   - `index_name` via metadata (for local adapter) or fallback to id
 */
export function useKbsForAdapter(adapterId: number | null | undefined) {
  const { data: adapters = [] } = useKbAdapters();

  // Memoize the adapter record lookup
  const adapterRecord = useMemo(
    () => (adapterId ? adapters.find((a) => a.adapter_id === adapterId) : undefined),
    [adapters, adapterId]
  );

  const query = useQuery({
    queryKey: adapterId != null ? unifiedKbKeys.kbsForAdapter(adapterId) : ["_disabled", adapterId],
    enabled: adapterId != null,
    queryFn: async (): Promise<KnowledgeBase[]> => {
      if (adapterId == null) return [];
      try {
        const response = await unifiedKBService.listKnowledgeBases(adapterId, {
          pageSize: 500,
        });
        const items: UnifiedKnowledgeBase[] = Array.isArray(response.list)
          ? response.list
          : [];
        return items.map((u) => mapUnifiedKbToLegacy(u, adapterRecord));
      } catch (error: any) {
        log.error(`Failed to fetch KBs for adapter ${adapterId}:`, error);
        return [];
      }
    },
    staleTime: 30_000,
    gcTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });

  return { ...query, adapterRecord };
}

/**
 * Map UnifiedKnowledgeBase → legacy-shape KnowledgeBase.
 *
 * Only the fields used by KB chip rendering + downstream `kb_refs` construction
 * are populated; the rest get defensive defaults. Adapter metadata is enriched
 * from the supplied UnifiedAdapter record so consumers get `source` and
 * `adapter_id`/`adapter_name` for free.
 */
function mapUnifiedKbToLegacy(
  u: UnifiedKnowledgeBase,
  adapter?: UnifiedAdapter
): KnowledgeBase {
  const metadata = (u.metadata ?? {}) as Record<string, unknown>;
  const kbId = String(u.knowledge_base_id);
  return {
    id: kbId,
    name: u.name,
    display_name: u.name,
    description: u.description || "",
    documentCount: u.document_count || 0,
    chunkCount: u.chunk_count || 0,
    createdAt: (metadata.create_time as string) || null,
    updatedAt: (metadata.update_time as string) || null,
    embeddingModel: u.embedding_model || "unknown",
    avatar: "",
    chunkNum: 0,
    language: "",
    nickname: "",
    parserId: "",
    permission: "",
    tokenNum: 0,
    source: adapter?.platform || u.platform || "external",
    tenant_id: (metadata.tenant_id as string) || "",
    index_name: (metadata.index_name as string) || kbId,
    adapter_id: adapter?.adapter_id,
    adapter_name: adapter?.name,
  };
}
