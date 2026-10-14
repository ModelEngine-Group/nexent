"use client";

import { Typography } from "antd";

interface NavigationRailLabelProps {
  expanded: boolean;
  label: string;
}

export function NavigationRailLabel({
  expanded,
  label,
}: NavigationRailLabelProps) {
  if (!expanded) return null;
  return (
    <Typography.Text
      ellipsis={{ tooltip: label }}
      className="!my-0 !ml-2 min-w-0 flex-1 !text-left !text-sm !font-normal !leading-[22px] !tracking-[0px] !text-[#191919]"
    >
      {label}
    </Typography.Text>
  );
}
