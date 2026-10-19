// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";

export type ResourceViewMode = "list" | "card";

export interface ResourceItemData<T = unknown> {
  key: string;
  name: string;
  description?: string;
  tags?: readonly string[];
  badges?: readonly string[];
  metadata?: readonly { key: string; label: string; value: string | number }[];
  raw: T;
}

export interface ResourceItemContext {
  viewMode: ResourceViewMode;
  selected: boolean;
  disabled: boolean;
}

export interface ResourceItemSlots<T> {
  renderTags?: (
    item: ResourceItemData<T>,
    context: ResourceItemContext
  ) => ReactNode;
  renderDescription?: (
    item: ResourceItemData<T>,
    context: ResourceItemContext
  ) => ReactNode;
  /** Noninteractive status or source displayed independently at the title's end. */
  renderTitleTrailing?: (
    item: ResourceItemData<T>,
    context: ResourceItemContext
  ) => ReactNode;
  renderMetadata?: (
    item: ResourceItemData<T>,
    context: ResourceItemContext
  ) => ReactNode;
  renderActions?: (
    item: ResourceItemData<T>,
    context: ResourceItemContext
  ) => ReactNode;
  renderContent?: (
    item: ResourceItemData<T>,
    context: ResourceItemContext
  ) => ReactNode;
}
