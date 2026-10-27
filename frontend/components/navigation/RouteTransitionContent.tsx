// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { ReactNode } from "react";
import { RouteLoadingSkeleton } from "@/components/common/RouteLoadingSkeleton";

interface RouteTransitionContentProps {
  pendingPath: string | null;
  children: ReactNode;
}

export function RouteTransitionContent({
  pendingPath,
  children,
}: RouteTransitionContentProps) {
  return (
    <div className="relative h-full min-h-0">
      <div
        className="h-full min-h-0"
        style={pendingPath ? { visibility: "hidden" } : undefined}
        inert={!!pendingPath}
        aria-hidden={pendingPath ? true : undefined}
      >
        {children}
      </div>
      {pendingPath && (
        <div className="absolute inset-0 z-20 overflow-auto">
          <RouteLoadingSkeleton pathname={pendingPath} />
        </div>
      )}
    </div>
  );
}
