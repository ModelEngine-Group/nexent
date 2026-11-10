// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export type ResourceType = "agent" | "mcp" | "skill";
export type ResourceRepositoryTab = ResourceType | "review";
export type ResourceRepositoryView = "repository" | "mine";

export interface ResourceRepositoryTarget {
  tab: ResourceRepositoryTab;
  view?: ResourceRepositoryView;
  resourceType?: ResourceType;
  repositoryId?: string;
  reviewId?: string;
  agentId?: string;
  skillId?: string;
  sourceMcpId?: string;
  onboarding?: string;
}

export type ResourceRepositoryParseResult =
  | { valid: true; target: ResourceRepositoryTarget }
  | { valid: false; error: "invalid_parameter" | "conflicting_target" };
