// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Form, InputNumber } from "antd";
import { useTranslation } from "react-i18next";

/** Shared capacity inputs for add, batch configuration and saved outlet editing. */
export function ModelCapacityFields({
  contextWindow,
  outputLimit,
  onChange,
}: {
  contextWindow?: number | null;
  outputLimit?: number | null;
  onChange: (
    key: "combined_window" | "output_limit",
    value: number | null
  ) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="grid grid-cols-2 gap-x-3">
      {(["combined_window", "output_limit"] as const).map((key) => {
        const label = t(
          key === "combined_window"
            ? "modelProfile.combined_window"
            : "modelProfile.maximumOutput"
        );
        return (
          <Form.Item
            key={key}
            label={label}
            tooltip={
              key === "output_limit"
                ? t("modelProfile.inheritedOutputLimit")
                : undefined
            }
          >
            <InputNumber
              className="!w-full"
              aria-label={label}
              min={1}
              precision={0}
              value={key === "combined_window" ? contextWindow : outputLimit}
              onChange={(value) => onChange(key, value)}
            />
          </Form.Item>
        );
      })}
    </div>
  );
}
