// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import ResizableTableHeader, {
  type ResizableTableHeaderProps,
} from "@/components/table/ResizableTableHeader";

export type AgentTableHeaderProps = ResizableTableHeaderProps;

export default function AgentTableHeader(props: AgentTableHeaderProps) {
  return (
    <ResizableTableHeader
      {...props}
      resizeHandleClassName="agent-table-resize-handle"
    />
  );
}
