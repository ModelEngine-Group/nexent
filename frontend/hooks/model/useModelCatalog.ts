import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { modelService } from "@/services/modelService";
import {
  ModelCatalogProviderInfo,
  ModelCatalogModelEntry,
  ModelCatalogProfile,
  ModelCatalogFullPayload,
  ModelType,
} from "@/types/modelConfig";

/**
 * React hook for the preset Model Catalog (预置模型目录).
 *
 * Uses a SINGLE network call to GET /model/catalog/all which returns every
 * provider + model + profile in one payload.  All filtering and single
 * profile lookups are derived in-memory, so the Add-Model dropdowns and
 * prefilling dialog no longer trigger multiple HTTP requests.
 *
 * Provides:
 *   - `providers`: list of providers that have at least 1 preset model
 *   - `getModelsForProvider(provider, modelType?)`: per-provider model list,
 *     filtered by model_type when provided.  Uses client-side filter.
 *   - `getProfile(provider, modelName)`: single-model profile for prefilling
 *     the Add-Model dialog form (client-side lookup, zero latency).
 *
 * Every call degrades gracefully: if the backend does not ship the catalog
 * module, or the JSON is malformed/missing, `catalogAvailable` returns false
 * and arrays are empty.  The UI can use this flag to skip rendering the
 * "From preset" entry-point entirely.
 */
export function useModelCatalog(options?: { staleTime?: number }) {
  const queryClient = useQueryClient();
  const staleTime = options?.staleTime ?? 5 * 60_000; // 5 min

  // --- Single fetch: full catalog payload -------------------------------
  const fullCatalogQuery = useQuery({
    queryKey: ["modelCatalog", "all"],
    queryFn: async () => modelService.getFullCatalog(),
    staleTime,
    throwOnError: false,
  });

  const catalog: ModelCatalogFullPayload =
    fullCatalogQuery.data?.catalog ??
    { version: "0.0.0", metadata: {}, providers: [] };
  const catalogAvailable: boolean =
    fullCatalogQuery.data?.catalogAvailable ?? false;

  // --- Derived providers list -------------------------------------------
  const providers: ModelCatalogProviderInfo[] = useMemo(
    () => catalog.providers.map((block) => block.provider_info),
    [catalog.providers]
  );

  // Provider key -> provider info lookup for fast access in dropdowns
  const providerByKey = useMemo(() => {
    const map = new Map<string, ModelCatalogProviderInfo>();
    providers.forEach((p) => map.set(p.provider_key, p));
    return map;
  }, [providers]);

  // Provider key -> model entries lookup for fast filtering/lookups
  const modelsByProviderKey = useMemo(() => {
    const map = new Map<string, ModelCatalogModelEntry[]>();
    catalog.providers.forEach((block) => {
      map.set(block.provider_info.provider_key, block.models ?? []);
    });
    return map;
  }, [catalog.providers]);

  // --- models per provider (local filter, no network) -------------------
  function filterModelsForProvider(
    provider: string | null | undefined,
    filterModelType?: ModelType
  ): ModelCatalogModelEntry[] {
    if (!provider) return [];
    const all = modelsByProviderKey.get(provider) ?? [];
    if (!filterModelType) return all;
    return all.filter((entry) => entry.profile.model_type === filterModelType);
  }

  /**
   * Hook-style model list accessor.  The returned shape mirrors a
   * react-query UseQueryResult so callers that previously used the
   * network-backed useModelsForProvider do not need to change.
   */
  function useModelsForProvider(
    provider: string | null | undefined,
    filterModelType?: ModelType,
    queryOptions?: { enabled?: boolean }
  ) {
    const enabled =
      !!provider &&
      catalogAvailable !== false &&
      (queryOptions?.enabled ?? true);

    const models = useMemo(
      () => (enabled ? filterModelsForProvider(provider, filterModelType) : []),
      // eslint-disable-next-line react-hooks/exhaustive-deps
      [provider, filterModelType, enabled, modelsByProviderKey]
    );

    return {
      ...fullCatalogQuery,
      data: { models, catalogAvailable },
    };
  }

  function getModelsForProvider(
    provider: string,
    filterModelType?: ModelType
  ): ModelCatalogModelEntry[] {
    // If the full catalog has not loaded yet, kick off a background refetch
    // and return an empty list for the current render.  Callers will
    // re-render once react-query delivers the data.
    if (!fullCatalogQuery.data && fullCatalogQuery.status === "pending") {
      void fullCatalogQuery.refetch().catch(() => undefined);
      return [];
    }
    return filterModelsForProvider(provider, filterModelType);
  }

  // --- single model profile (client-side lookup) ------------------------
  function findProfile(
    provider: string | null | undefined,
    modelName: string | null | undefined
  ): ModelCatalogProfile | null {
    if (!provider || !modelName) return null;
    const entries = modelsByProviderKey.get(provider);
    if (!entries || entries.length === 0) return null;
    const hit = entries.find((e) => e.model_name === modelName);
    return hit?.profile ?? null;
  }

  function useProfile(
    provider: string | null | undefined,
    modelName: string | null | undefined,
    queryOptions?: { enabled?: boolean }
  ) {
    const enabled =
      !!provider &&
      !!modelName &&
      catalogAvailable !== false &&
      (queryOptions?.enabled ?? true);

    const profile = useMemo(
      () => (enabled ? findProfile(provider, modelName) : null),
      // eslint-disable-next-line react-hooks/exhaustive-deps
      [provider, modelName, enabled, modelsByProviderKey]
    );

    return {
      ...fullCatalogQuery,
      data: { profile, catalogAvailable },
    };
  }

  function getProfile(
    provider: string,
    modelName: string
  ): ModelCatalogProfile | null {
    if (!fullCatalogQuery.data && fullCatalogQuery.status === "pending") {
      void fullCatalogQuery.refetch().catch(() => undefined);
      return null;
    }
    return findProfile(provider, modelName);
  }

  function invalidateAll() {
    return queryClient.invalidateQueries({
      queryKey: ["modelCatalog"],
    });
  }

  return {
    // Raw react-query state (backward-compatible: callers used `providersQuery`
    // as the primary "is catalog loading" signal).
    providersQuery: fullCatalogQuery as any,
    // Computed values
    providers,
    catalogAvailable,
    providerByKey,
    // Per-provider model list
    useModelsForProvider,
    getModelsForProvider,
    // Single profile lookup
    useProfile,
    getProfile,
    // Mutation helpers
    invalidateAll,
  };
}
