// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ResourceType } from "./resourceRepository";

export type ReviewStatus = "pending_review" | "approved" | "rejected";
export type ReviewDecision = "approve" | "reject";
export interface ResourceReview {
  resource_type: ResourceType;
  review_id: string;
  source_resource_id: string;
  version_no: number | null;
  repository_id: string | null;
  tenant_id: string;
  tenant_name: string | null;
  name: string;
  description: string | null;
  version_label: string | null;
  status: ReviewStatus;
  submitted_user_id: string | null;
  submitter: {
    user_id: string | null;
    display_name: string | null;
    cas_username?: string | null;
  };
  submitted_at: string | null;
  published_at: string | null;
  submit_description: string | null;
  review_comment: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  current_repository_status: string | null;
  allowed_actions: ReviewDecision[];
}
export interface ResourceReviewDetail extends ResourceReview {
  resource_detail: {
    agent_id?: number;
    version_no?: number;
    agents?: {
      name?: string;
      description?: string;
      prompt?: string;
      tools?: string[];
    }[];
    skill_id?: number;
    file_manifest?: { path: string; size_bytes: number }[];
    file_count?: number;
    files_unavailable?: boolean;
    readme?: string | null;
    tags?: string[];
    transport_type?: string;
    server_url?: string | null;
    shared_fields?: Record<string, boolean>;
    sensitive_fields?: { name: string; configured: boolean; masked: boolean }[];
  };
}
export interface ResourceReviewQuery {
  type: ResourceType | "all";
  status: ReviewStatus | "all";
  search: string;
  page: number;
  page_size: number;
}
export interface ResourceReviewList {
  items: ResourceReview[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
}

export interface ResourceReviewSubmission {
  resource_type: ResourceType;
  source_resource_id: string;
  version_no?: number;
  submit_description?: string | null;
  listing_fields?: Record<string, unknown>;
}
