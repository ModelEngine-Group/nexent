// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";
import type { FC } from "react";
import type { Unstable_DirectiveSegment } from "@assistant-ui/react";
type IconComponent = FC<{ className?: string }>;

export const DirectiveChip: FC<{
  segment: Extract<Unstable_DirectiveSegment, { kind: "mention" }>;
  iconMap?: Record<string, IconComponent>;
  fallbackIcon?: IconComponent;
  onClick?: (
    segment: Extract<Unstable_DirectiveSegment, { kind: "mention" }>
  ) => void;
}> = ({ segment, iconMap, fallbackIcon, onClick }) => {
  const Icon = iconMap?.[segment.type] ?? fallbackIcon;
  const content = (
    <>
      {Icon && <Icon className="size-3" />}
      {segment.label}
    </>
  );
  const className =
    "bg-muted text-foreground mx-0.5 inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 align-middle text-xs font-medium";

  return onClick ? (
    <button
      type="button"
      data-slot="directive-chip"
      data-type={segment.type}
      title={segment.id}
      aria-label={`${segment.label}: ${segment.id}`}
      className={`${className} cursor-pointer hover:bg-muted/70`}
      onClick={() => onClick(segment)}
    >
      {content}
    </button>
  ) : (
    <span
      data-slot="directive-chip"
      data-type={segment.type}
      title={segment.id}
      aria-label={`${segment.label}: ${segment.id}`}
      className={className}
    >
      {content}
    </span>
  );
};
