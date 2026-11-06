// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Typography } from "antd";

interface NavigationRailLabelProps {
  expanded: boolean;
  label: string;
  selected?: boolean;
  variant?: "label" | "title";
}

export function NavigationRailLabel({
  expanded,
  label,
  selected = false,
  variant = "label",
}: NavigationRailLabelProps) {
  if (!expanded) return null;
  return (
    <Typography.Text
      ellipsis={{ tooltip: label }}
      className={`!my-0 !block min-w-0 max-w-full flex-1 !text-left !tracking-[0px] transition-colors duration-150 ease-out ${variant === "title" ? "!ml-0 !text-lg !font-bold !leading-6 !text-[var(--navigation-foreground)]" : `!ml-[-6px] !text-sm !font-normal !leading-[22px] ${selected ? "!text-[var(--navigation-foreground)]" : "!text-[var(--navigation-muted)]"} group-hover:!text-[var(--navigation-foreground)] group-focus-visible:!text-[var(--navigation-foreground)]`}`}
    >
      {label}
    </Typography.Text>
  );
}
