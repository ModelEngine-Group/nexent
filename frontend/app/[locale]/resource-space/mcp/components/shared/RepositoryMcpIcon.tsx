// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Puzzle } from "lucide-react";

import { McpDeploymentType } from "@/const/mcpTools";

export default function RepositoryMcpIcon({
  deploymentType,
}: {
  deploymentType: McpDeploymentType;
}) {
  const tone =
    deploymentType === McpDeploymentType.REMOTE_LINK
      ? "bg-[#EEE0F7] text-[#743E9C]"
      : deploymentType === McpDeploymentType.API
        ? "bg-[#E0F2D2] text-[#346522]"
        : "bg-[#D0D8FD]/50 text-[#1F55B5]";

  return (
    <span
      aria-hidden="true"
      className={`flex size-12 shrink-0 items-center justify-center rounded ${tone}`}
    >
      <Puzzle size={24} />
    </span>
  );
}
