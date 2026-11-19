// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Button, Tooltip } from "antd";
import { CopyPlus, PackageX } from "lucide-react";

interface CardAction {
  label: string;
  onClick: () => void;
  loading?: boolean;
  disabled?: boolean;
  hint?: string;
}

export default function RepositoryCardActions({
  primary,
  takeDown,
}: {
  primary?: CardAction;
  takeDown?: CardAction;
}) {
  if (!primary && !takeDown) return null;
  return (
    <div
      className="inline-flex items-center gap-1"
      onClick={(event) => event.stopPropagation()}
    >
      {primary && (
        <Tooltip title={primary.hint || primary.label}>
          <span className="inline-flex">
            <Button
              type="text"
              className="size-8 shrink-0"
              aria-label={primary.label}
              icon={<CopyPlus className="size-4" aria-hidden />}
              loading={primary.loading}
              disabled={primary.disabled}
              onClick={primary.onClick}
            />
          </span>
        </Tooltip>
      )}
      {takeDown && (
        <Tooltip title={takeDown.label}>
          <span className="inline-flex">
            <Button
              type="text"
              danger
              className="size-8 shrink-0"
              aria-label={takeDown.label}
              icon={<PackageX className="size-4" aria-hidden />}
              loading={takeDown.loading}
              disabled={takeDown.disabled}
              onClick={takeDown.onClick}
            />
          </span>
        </Tooltip>
      )}
    </div>
  );
}
