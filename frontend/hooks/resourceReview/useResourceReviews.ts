// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { RESOURCE_REPOSITORY_PERMISSION_ROUTE } from "@/const/resourceRepository";
import {
  decideResourceReview,
  fetchResourceReview,
  fetchResourceReviews,
} from "@/services/resourceReviewService";
import type { ResourceType } from "@/types/resourceRepository";
import type {
  ResourceReviewQuery,
  ReviewDecision,
} from "@/types/resourceReview";

export function useResourceReviews(
  query: ResourceReviewQuery,
  type?: ResourceType,
  id?: string,
  detailOnly = false
) {
  const { user, isAuthzReady, canAccessRoute } = useAuthorizationContext();
  const enabled =
    isAuthzReady &&
    !!user &&
    canAccessRoute(RESOURCE_REPOSITORY_PERMISSION_ROUTE);
  const identity = [user?.id, user?.tenantId, user?.role];
  const client = useQueryClient();
  const list = useQuery({
    queryKey: ["resourceReviews", ...identity, query],
    queryFn: () => fetchResourceReviews(query),
    enabled: enabled && !detailOnly,
  });
  const detail = useQuery({
    queryKey: ["resourceReview", ...identity, type, id],
    queryFn: () => fetchResourceReview(id!),
    enabled: enabled && !!id,
  });
  const decision = useMutation({
    mutationFn: (input: {
      type: ResourceType;
      id: string;
      decision: ReviewDecision;
      reason: string;
    }) => decideResourceReview(input.id, input.decision, input.reason),
    retry: false,
    onSettled: async () => {
      await client.invalidateQueries({
        predicate: ({ queryKey }) => {
          const key = String(queryKey[0]);
          return /resourceReview|Repository|myEditable|mcp|skills|agents/i.test(
            key
          );
        },
      });
    },
  });
  return { list, detail, decision };
}
