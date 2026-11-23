// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { LucideIcon } from "lucide-react";

export interface AgentSuggestionItem {
  id: string;
  title: string;
  prompt: string;
  description?: string;
  icon?: LucideIcon;
  disabled?: boolean;
}

export interface AgentSuggestionStyleProps {
  suggestions: readonly AgentSuggestionItem[];
  onSelect: (prompt: string, suggestion: AgentSuggestionItem) => void;
  disabled?: boolean;
  className?: string;
}

export type AgentSuggestionVariant = "text" | "card";

export interface AgentSuggestionProps extends AgentSuggestionStyleProps {
  variant: AgentSuggestionVariant;
}
