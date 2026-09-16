"use client";

import { useQuery } from "@tanstack/react-query";

import { modelService } from "@/services/modelService";
import type { InferenceFieldSpecsByType } from "@/types/modelConfig";

/**
 * v2.6.0: React hook that fetches and caches the fixed inference field specs
 * (returned by GET /model/catalog/inference_field_specs).
 *
 * The payload is shared across every caller of `ModelAdvancedSettings` so the
 * per-type field list is fetched exactly once per session. Callers can pass
 * `enabled: false` to skip the fetch (e.g. until a modal opens).
 */
export function useInferenceFieldSpecs(options?: {
  enabled?: boolean;
  staleTime?: number;
}) {
  const query = useQuery({
    queryKey: ["modelCatalog", "inferenceFieldSpecs"],
    queryFn: async (): Promise<InferenceFieldSpecsByType> =>
      modelService.getInferenceFieldSpecs(),
    staleTime: options?.staleTime ?? 10 * 60_000, // 10 min default
    enabled: options?.enabled ?? true,
    throwOnError: false,
  });

  return {
    specs: query.data ?? {},
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
