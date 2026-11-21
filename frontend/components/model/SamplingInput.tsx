// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useRef } from "react";
import { ConfigProvider, InputNumber } from "antd";
import { useTranslation } from "react-i18next";

import {
  TOP_P_STEP,
  samplingErrorKey,
  validSampling,
  type SamplingField,
} from "@/lib/modelSamplingParameters";

function formatSamplingNumber(
  value: number | undefined,
  { userTyping, input }: { userTyping: boolean; input: string }
) {
  return userTyping ? input : String(value ?? "");
}

export function SamplingInput({
  field,
  label,
  value,
  inherited,
  schema = {},
  disabled,
  className,
  showAllowedRange = false,
  onChange,
  onCommit,
}: {
  field: SamplingField;
  label: string;
  value: unknown;
  inherited?: unknown;
  schema?: Record<string, unknown>;
  disabled?: boolean;
  className?: string;
  showAllowedRange?: boolean;
  onChange: (value: number | null) => void;
  onCommit?: (value: number | null) => void;
}) {
  const { t } = useTranslation();
  const edited = useRef(false);
  const number = typeof value === "number" ? value : null;
  const invalid = !validSampling(field, value ?? inherited, schema);
  const step = field === "top_p" ? TOP_P_STEP : 0.1;
  const max = Math.min(
    field === "top_p" ? 1 : 2,
    typeof schema.maximum === "number" ? schema.maximum : Infinity
  );
  const minimum = Math.max(
    0,
    typeof schema.minimum === "number" ? schema.minimum : 0
  );
  const min = Math.min(
    max,
    field === "top_p" ? Math.max(TOP_P_STEP, minimum) : minimum
  );
  const range = `${minimum}–${max}`;
  const rangeHint =
    field === "top_p" && minimum === 0
      ? t("modelParams.rangeWithoutZero", { range })
      : range;

  const commit = () => {
    if (!edited.current) return;
    edited.current = false;
    onCommit?.(number);
  };

  return (
    <div className={`min-w-0 ${className ?? "flex-1"}`}>
      <ConfigProvider theme={{ components: { InputNumber: { handleVisible: true } } }}>
        <InputNumber<number>
          aria-label={label}
          aria-invalid={invalid}
          className="!w-full"
          controls
          min={min}
          max={max}
          step={step}
          formatter={formatSamplingNumber}
          changeOnBlur={false}
          value={number}
          placeholder={
            typeof inherited === "number"
              ? String(inherited)
              : showAllowedRange
                ? rangeHint
                : t("modelProfile.serviceSamplingDefault")
          }
          disabled={disabled}
          status={invalid ? "error" : undefined}
          onInput={(text) => {
            // Numeric drafts may be outside the stepper range, such as a
            // manually entered Top P below 0.01 or a value needing repair.
            const next = text.trim() === "" ? null : Number(text);
            if (next === number || (next !== null && !Number.isFinite(next))) return;
            edited.current = true;
            onChange(next);
          }}
          onStep={(stepped, { offset, type }) => {
            const next =
              number === null && typeof inherited === "number"
                ? Math.min(
                    max,
                    Math.max(
                      min,
                      Number(
                        (inherited + (type === "up" ? 1 : -1) * Number(offset)).toPrecision(15)
                      )
                    )
                  )
                : stepped;
            if (!validSampling(field, next, schema)) return;
            edited.current = false;
            onChange(next);
            onCommit?.(next);
          }}
          onBlur={commit}
          onPressEnter={(event) => {
            if (!onCommit) return;
            event.preventDefault();
            commit();
          }}
        />
      </ConfigProvider>
      {invalid && (
        <p role="alert" className="text-xs text-destructive">
          {t(samplingErrorKey(field))}
        </p>
      )}
    </div>
  );
}
