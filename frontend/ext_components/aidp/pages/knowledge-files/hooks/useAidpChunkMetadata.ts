// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useQuery } from "@tanstack/react-query";

import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";
import type { AidpOntologyMetadataField } from "@/ext_components/aidp/shared/types/ontology";

/**
 * Resolve a knowledge base's ontology binding.
 *
 * Chunk metadata fields and tag choices both come from the bound ontology
 * domain, so the chunk drawers only offer those editors while a binding
 * exists. A failed lookup degrades to "no binding" (the callers then hide the
 * metadata editor) instead of blocking the chunk form.
 */
export const useKbOntologyBinding = (kdsId: string) => {
  const scope = useAidpQueryScope();
  return useQuery({
    queryKey: [...scope.key, "kb-ontology-binding", kdsId],
    queryFn: async ({ signal }) =>
      aidpOntologyService.getKnowledgeBaseBinding(kdsId, signal),
    enabled: scope.enabled && !!kdsId,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
};

/** Metadata field definitions of the bound ontology domain (up to 100). */
export const useOntologyMetadataSchema = (
  odId: number | string | null | undefined
) => {
  const scope = useAidpQueryScope();
  return useQuery<AidpOntologyMetadataField[]>({
    queryKey: [...scope.key, "ontology-metadata-schema", odId],
    queryFn: async ({ signal }) => {
      const response = await aidpOntologyService.listMetadataFields(
        String(odId),
        1,
        100,
        undefined,
        signal
      );
      return response.value;
    },
    enabled: scope.enabled && odId !== null && odId !== undefined,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
};

/** Entity display names usable as chunk tags (first page, up to 100). */
export const useOntologyEntityOptions = (
  odId: number | string | null | undefined
) => {
  const scope = useAidpQueryScope();
  return useQuery<string[]>({
    queryKey: [...scope.key, "ontology-entity-options", odId],
    queryFn: async ({ signal }) => {
      const response = await aidpOntologyService.listEntities(
        String(odId),
        1,
        100,
        undefined,
        "entity",
        signal
      );
      return Array.from(
        new Set(
          response.value
            .map((entity) => (entity.display_name || "").trim())
            .filter(Boolean)
        )
      );
    },
    enabled: scope.enabled && odId !== null && odId !== undefined,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
};
