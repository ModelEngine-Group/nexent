// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useQuery } from "@tanstack/react-query";

import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import { useAidpQueryScope } from "@/ext_components/aidp/shared/hooks/useAidpQueryScope";

/**
 * True only when the deployment explicitly marks the local demo data source.
 * Components use it to show demo-only UCD values and never present them as
 * real AIDP facts.
 */
export const useAidpOntologyDemoMode = (): boolean => {
  const scope = useAidpQueryScope();
  const query = useQuery({
    queryKey: [...scope.key, "ontology-demo-mode"],
    queryFn: () => aidpOntologyService.getDemoMode(),
    enabled: scope.enabled,
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
  return query.data?.demo === true;
};

export default useAidpOntologyDemoMode;
