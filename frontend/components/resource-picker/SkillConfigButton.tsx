// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { MouseEventHandler } from "react";
import { Settings } from "lucide-react";
import { useTranslation } from "react-i18next";

export function SkillConfigButton({
  hasParameters,
  disabled = false,
  onClick,
}: {
  hasParameters: boolean;
  disabled?: boolean;
  onClick: MouseEventHandler<HTMLButtonElement>;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      disabled={disabled || !hasParameters}
      onClick={onClick}
      aria-label={t("skillPool.configure")}
      title={t(
        hasParameters
          ? "skillPool.configure"
          : "resourcePicker.skill.noParameters"
      )}
      className="flex size-7 shrink-0 items-center justify-center rounded-base text-[var(--color-icon-secondary)] transition-colors enabled:hover:bg-[var(--color-hover)] enabled:hover:text-[var(--color-icon-hover)] enabled:active:text-[var(--color-icon-active)] disabled:cursor-not-allowed disabled:text-[var(--color-icon-disabled)]"
    >
      <Settings className="size-4" />
    </button>
  );
}
