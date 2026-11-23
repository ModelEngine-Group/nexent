// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";

export default function ResourcePanelTitle({
  title,
  icon,
  subtitle,
}: {
  title: string;
  icon: ReactNode;
  subtitle?: ReactNode;
}) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <div className="shrink-0">{icon}</div>
      <div className="min-w-0">
        <h2 className="break-words text-lg leading-6 font-semibold text-foreground">
          {title}
        </h2>
        {subtitle && (
          <div className="mt-1 break-words text-body-1 font-normal text-muted-foreground">
            {subtitle}
          </div>
        )}
      </div>
    </div>
  );
}
