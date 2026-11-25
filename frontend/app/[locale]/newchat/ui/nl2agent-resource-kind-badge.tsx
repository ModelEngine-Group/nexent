// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { HardDrive, Plug, Sparkles } from "lucide-react";

interface Nl2AgentResourceKindBadgeProps {
  kind: "Local" | "MCP" | "Skill" | "Tool";
}

const local = {
  Icon: HardDrive,
  style: "border-gray-200 bg-gray-100 text-gray-500",
};

const kinds = {
  Local: local,
  Tool: local,
  MCP: { Icon: Plug, style: "border-blue-200 bg-blue-50 text-blue-600" },
  Skill: {
    Icon: Sparkles,
    style: "border-emerald-200 bg-emerald-50 text-emerald-600",
  },
};

export function Nl2AgentResourceKindBadge({
  kind,
}: Nl2AgentResourceKindBadgeProps) {
  const { Icon, style } = kinds[kind];
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] leading-none ${style}`}
    >
      <Icon className="size-3" aria-hidden="true" />
      {kind}
    </span>
  );
}
