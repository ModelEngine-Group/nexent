// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { ReactNode } from "react";

interface AgentWelcomeProps {
  title: string;
  greeting?: string;
  icon?: ReactNode;
  children?: ReactNode;
}

export function AgentWelcome({
  title,
  greeting,
  icon,
  children,
}: AgentWelcomeProps) {
  return (
    <div className="mx-auto flex h-full min-h-0 w-full max-w-[890px] flex-col justify-center gap-32 px-4 py-4 text-[#191919]">
      <div className="flex shrink-0 flex-col items-center gap-4 text-center">
        <div className="flex items-center justify-center gap-4">
          {icon}
          <h1 className="text-[28px] font-bold leading-9">{title}</h1>
        </div>
        {greeting && <p className="text-base leading-6">{greeting}</p>}
      </div>
      {children && <div className="w-full min-w-0">{children}</div>}
    </div>
  );
}
