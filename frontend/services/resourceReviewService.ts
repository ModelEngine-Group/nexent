// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";
import { getAuthHeaders } from "@/lib/auth";
import type {
  ResourceReview,
  ResourceReviewDetail,
  ResourceReviewList,
  ResourceReviewQuery,
  ReviewDecision,
  ResourceReviewSubmission,
} from "@/types/resourceReview";

export class ReviewRequestError extends Error {
  constructor(public readonly status: number) {
    super(`Review request failed (${status})`);
  }
}

async function request<T>(url: string, payload?: unknown): Promise<T> {
  const response = await fetchWithErrorHandling(url, {
    method: payload ? "POST" : "GET",
    headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
    ...(payload ? { body: JSON.stringify(payload) } : {}),
  });
  if (!response.ok) throw new ReviewRequestError(response.status);
  return response.json();
}

export const fetchResourceReviews = (query: ResourceReviewQuery) =>
  request<ResourceReviewList>(API_ENDPOINTS.resourceReviews.list(query));
export const fetchResourceReview = (id: string) =>
  request<ResourceReviewDetail>(API_ENDPOINTS.resourceReviews.detail(id));
export const decideResourceReview = (
  id: string,
  decision: ReviewDecision,
  reason: string
) =>
  request<ResourceReview>(API_ENDPOINTS.resourceReviews.decision(id), {
    decision,
    reason: reason.trim() || null,
  });

export const submitResourceReview = (payload: ResourceReviewSubmission) =>
  request<ResourceReview>(API_ENDPOINTS.resourceReviews.submit, payload);
