// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";

export function ModelThinkingToggle({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (value: boolean) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <span className="text-sm">{t("chat.modelSelector.deepThinking")}</span>
      <button
        type="button"
        role="switch"
        aria-label={t("chat.modelSelector.deepThinking")}
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative h-5 w-9 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
          checked ? "bg-primary" : "bg-muted-foreground/40"
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 size-4 rounded-full bg-white shadow-sm transition-transform",
            checked ? "left-[18px]" : "left-0.5"
          )}
        />
      </button>
    </div>
  );
}
