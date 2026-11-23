// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { ReactNode } from "react";
import { Tooltip } from "antd";
import { StandardQuestionIcon } from "@/components/common/StandardQuestionIcon";

interface AgentSettingHintProps {
  label: string;
  hint: string;
  children: ReactNode;
}

export function AgentSettingHint({
  label,
  hint,
  children,
}: AgentSettingHintProps) {
  return (
    <div className="flex max-w-full items-center gap-2">
      {children}
      <Tooltip title={hint}>
        <button
          type="button"
          aria-label={label}
          className="inline-flex shrink-0 cursor-help items-center justify-center border-0 bg-transparent p-0 text-sm text-gray-400 hover:text-gray-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <StandardQuestionIcon aria-hidden />
        </button>
      </Tooltip>
    </div>
  );
}
