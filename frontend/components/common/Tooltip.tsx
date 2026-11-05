// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";
import type { ComponentProps } from "react";
import { TooltipContent as BaseContent } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
export * from "@/components/ui/tooltip";
export function TooltipContent({
  className,
  sideOffset = 4,
  ...props
}: ComponentProps<typeof BaseContent>) {
  return (
    <BaseContent
      {...props}
      sideOffset={sideOffset}
      className={cn("z-[var(--ui-layer-popover)]", className)}
    />
  );
}
