// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";
import type { ComponentProps } from "react";
import { Popover as Primitive } from "radix-ui";
import { PopoverContent as BaseContent } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
export * from "@/components/ui/popover";
export const PopoverArrow = Primitive.Arrow;
export function PopoverContent({
  className,
  ...props
}: ComponentProps<typeof BaseContent>) {
  return (
    <BaseContent
      {...props}
      className={cn("z-[var(--ui-layer-popover)]", className)}
    />
  );
}
