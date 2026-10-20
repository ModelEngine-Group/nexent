// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { ResourceDrawer, type ResourceDrawerProps } from "./ResourceDrawer";

/** Compatibility entry point for callers outside the current migration scope. */
export interface AddResourceDrawerProps extends ResourceDrawerProps {
  size?: number | string;
}

export function AddResourceDrawer({
  size,
  width = 760,
  ...props
}: AddResourceDrawerProps) {
  return <ResourceDrawer {...props} width={size ?? width} />;
}

export {
  CheckMark,
  SearchRow,
  SelectedChips,
  ListHeader,
  ResourceRow,
  ResourceTabs,
  ResourcePagination,
} from "./ResourceDrawer";
