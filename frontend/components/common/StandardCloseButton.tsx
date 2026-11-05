// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { X } from "lucide-react";

export interface StandardCloseButtonProps {
  ariaLabel: string;
  onClick: () => void;
}

export function StandardCloseButton({
  ariaLabel,
  onClick,
}: StandardCloseButtonProps) {
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      className="flex h-[14px] w-[14px] shrink-0 cursor-pointer items-center justify-center border-0 bg-transparent p-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
      onClick={onClick}
    >
      <X size={14} />
    </button>
  );
}
