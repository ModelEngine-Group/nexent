// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ComponentProps, CSSProperties } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface ConfigCardProps extends ComponentProps<typeof Card> {
  bodyStyle?: CSSProperties;
}

/** Shared surface for agent configuration sections, not a global Card API. */
export function ConfigCard({
  className,
  bodyStyle,
  children,
  ...props
}: ConfigCardProps) {
  return (
    <Card {...props} className={cn("border-0", className)}>
      <CardContent style={bodyStyle}>{children}</CardContent>
    </Card>
  );
}
