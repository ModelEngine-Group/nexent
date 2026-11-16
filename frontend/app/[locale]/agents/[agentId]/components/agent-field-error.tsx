// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { CircleAlert } from "lucide-react";

export function AgentFieldError({
  id,
  message,
}: {
  id: string;
  message: string;
}) {
  return (
    <span id={id} className="flex items-center gap-1 text-xs leading-5">
      <CircleAlert size={14} className="shrink-0" aria-hidden="true" />
      {message}
    </span>
  );
}
