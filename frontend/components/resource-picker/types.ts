// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

// Shared types for the "add resource" slide-out drawers (agent, knowledge, model, skill, tool).

export interface SelectedItem {
  id: string;
  label: string;
}

export interface ResourcePickerTab {
  key: string;
  label: string;
}

export interface TagOption {
  value: string;
  label: string;
}

/** Card entry for the "add agent" drawer. */
export interface AgentCardItem {
  id: string;
  /** Original numeric identity, independent of caller-defined selection keys. */
  agentId?: number;
  tagResourceId?: string;
  iconUrl?: string;
  name: string;
  description: string;
  iconBg?: string;
  version?: string;
  updatedAt?: string;
  online?: boolean;
  tags?: string[];
}

/** Row entry for the "add knowledge" drawer. */
export interface KnowledgeItem {
  id: string;
  name: string;
  category?: string;
  description: string;
  meta: string[];
}

/** Left-hand group entry for the "add model" drawer. */
export interface ModelGroup {
  key: string;
  label: string;
  icon: string;
  iconBg: string;
}

/** Model row entry for the "add model" drawer. */
export interface ModelItem {
  id: string;
  name: string;
  tags: string[];
  /** Lowercased modelFactory/source used to resolve a provider logo. */
  provider?: string;
}

/** Row entry shared by the "add skill" and "add tool" drawers. */
export interface ResourceRowItem {
  id: string;
  name: string;
  tags: string[];
  description: string;
  /** Render the name as a link-colored label (official / registry entries). */
  link?: boolean;
}
