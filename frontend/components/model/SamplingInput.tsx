// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Button, InputNumber } from "antd";
import { useTranslation } from "react-i18next";
import { TOP_P_STEP, samplingErrorKey, validSampling, type SamplingField } from "@/lib/modelSamplingParameters";

export function SamplingInput({
  field,
  label,
  value,
  inherited,
  schema = {},
  disabled,
  onChange,
}: {
  field: SamplingField;
  label: string;
  value: unknown;
  inherited?: unknown;
  schema?: Record<string, unknown>;
  disabled?: boolean;
  onChange: (value: number | null) => void;
}) {
  const { t } = useTranslation();
  const display = value ?? inherited;
  const invalid = !validSampling(field, display, schema);
  const step = field === "top_p" ? TOP_P_STEP : 0.1;
  const min = Math.max(
    field === "top_p" ? TOP_P_STEP : 0,
    typeof schema.minimum === "number" ? schema.minimum : 0
  );
  const max = Math.min(
    field === "top_p" ? 1 : 2,
    typeof schema.maximum === "number" ? schema.maximum : Infinity
  );
  const stepValue = (direction: number) =>
    Math.min(
      max,
      Math.max(
        min,
        Number(
          (
            (typeof display === "number" ? display : 0) +
            direction * step
          ).toPrecision(15)
        )
      )
    );
  const canStep = (direction: number) =>
    !disabled &&
    validSampling(field, stepValue(direction), schema) &&
    stepValue(direction) !== display;

  return (
    <div className="min-w-0 flex-1">
      <div className="flex gap-1">
        <InputNumber
          aria-label={label}
          aria-invalid={invalid}
          className="!w-full"
          controls={false}
          keyboard={false}
          changeOnBlur={false}
          value={typeof value === "number" ? value : null}
          placeholder={
            typeof inherited === "number"
              ? String(inherited)
              : t("modelProfile.serviceSamplingDefault")
          }
          disabled={disabled}
          status={invalid ? "error" : undefined}
          onChange={onChange}
        />
        {([-1, 1] as const).map((direction) => {
          const symbol = direction < 0 ? "−" : "+";
          return (
            <Button
              key={direction}
              aria-label={`${label} ${symbol}`}
              disabled={!canStep(direction)}
              onClick={() => onChange(stepValue(direction))}
            >
              {symbol}
            </Button>
          );
        })}
      </div>
      {invalid && (
        <p role="alert" className="text-xs text-destructive">
          {t(samplingErrorKey(field))}
        </p>
      )}
    </div>
  );
}
