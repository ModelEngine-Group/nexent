// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Typography } from "antd";

interface NavigationRailLabelProps {
  expanded: boolean;
  label: string;
  variant?: "label" | "title";
}

export function NavigationRailLabel({
  expanded,
  label,
  variant = "label",
}: NavigationRailLabelProps) {
  if (!expanded) return null;
  return (
    <Typography.Text
      ellipsis={{ tooltip: label }}
      className={`!my-0 !ml-0 !block min-w-0 max-w-full flex-1 !text-left !tracking-[0px] ${variant === "title" ? "!text-base !font-bold !leading-6 !text-[#1a1a1a]" : "!text-sm !font-normal !leading-[22px] !text-[#191919]"}`}
    >
      {label}
    </Typography.Text>
  );
}
