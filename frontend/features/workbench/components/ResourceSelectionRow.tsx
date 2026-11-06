// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";
import { ResourceItem } from "@/components/resource-picker/ResourceItem";

/** Compatibility adapter; selection rows share the configuration resource item. */
export function ResourceSelectionRow({
  title,
  description,
  tags = [],
  selected = false,
  disabled = false,
  disabledReason,
  onClick,
  actions,
}: {
  title: string;
  description?: string;
  tags?: readonly string[];
  selected?: boolean;
  disabled?: boolean;
  disabledReason?: string;
  onClick: () => void;
  actions?: ReactNode;
}) {
  return (
    <ResourceItem
      item={{ key: title, name: title, description, tags, raw: null }}
      selected={selected}
      disabled={disabled}
      disabledReason={disabledReason}
      onToggle={onClick}
      slots={{ renderActions: () => actions }}
    />
  );
}
