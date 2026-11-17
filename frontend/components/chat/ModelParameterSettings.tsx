// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Button, Popover, Slider } from "antd";
import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ModelParameterSettingsControl } from "@/types/modelParameterSettings";

import { TOP_P_STEP, validSampling, type SamplingField } from "@/lib/modelSamplingParameters";

function configuredValue(value: number | undefined, max: number) {
  return value != null && Number.isFinite(value) && value >= 0 && value <= max
    ? value
    : undefined;
}

export function ParameterLevel({
  label,
  value,
  inheritedValue,
  max,
  min = 0,
  disabled,
  field,
  schema,
  onClear,
  onChange,
}: {
  label: string;
  value?: number;
  inheritedValue?: number;
  max: number;
  min?: number;
  disabled?: boolean;
  field?: SamplingField;
  schema?: Record<string, unknown>;
  onClear?: () => void;
  onChange: (value: number) => void;
}) {
  const { t } = useTranslation();
  const topP = field === "top_p";
  const step = topP ? TOP_P_STEP : 0.1;
  const sliderMin = topP ? Math.min(max, Math.max(min, TOP_P_STEP)) : min;
  const displayValue = value ?? inheritedValue;
  const isValid = (next: number) =>
    field
      ? validSampling(field, next, { minimum: min, maximum: max, ...schema })
      : Number.isFinite(next) && next >= min && next <= max;
  const sliderDisabled =
    disabled || (topP && sliderMin === max && !isValid(max));
  const [text, setText] = useState(
    displayValue == null ? "" : String(displayValue)
  );
  const [error, setError] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [previousValue, setPreviousValue] = useState(displayValue);
  if (previousValue !== displayValue) {
    setPreviousValue(displayValue);
    setText(displayValue == null ? "" : String(displayValue));
    setError(false);
    setDirty(false);
  }
  const commit = () => {
    if (!dirty) return;
    if (!text.trim() && onClear) {
      setError(false);
      setDirty(false);
      setText(inheritedValue == null ? "" : String(inheritedValue));
      if (value !== undefined) onClear();
      return;
    }
    const next = Number(text);
    if (!text.trim() || !isValid(next)) {
      setError(true);
      return;
    }
    setError(false);
    setDirty(false);
    setText(String(next));
    if (next !== value) onChange(next);
  };
  const draftNumber = text.trim() ? Number(text) : displayValue;
  const sliderValue =
    draftNumber != null && isValid(draftNumber) ? draftNumber : null;
  const invalid = error || (field !== undefined && !!text.trim() && !isValid(Number(text)));
  return (
    <div className="space-y-1">
      <label className="text-sm">{label}</label>
      <div className="flex items-center gap-3">
        <Slider
          min={sliderMin}
          max={max}
          step={step}
          value={sliderValue ?? sliderMin}
          marks={
            sliderValue == null
              ? undefined
              : {
                  [sliderValue]: {
                    label: <span />,
                    style: { display: "none" },
                  },
                }
          }
          styles={
            sliderValue == null
              ? {
                  handle: { opacity: 0 },
                  track: { opacity: 0 },
                }
              : undefined
          }
          tooltip={
            sliderValue == null
              ? {
                  formatter: () => t("modelProfile.thinkingModeOption.default"),
                }
              : undefined
          }
          disabled={sliderDisabled}
          className="!m-0 min-w-0 flex-1 focus-within:ring-2 focus-within:ring-ring/50 [&_.ant-slider-dot]:hidden"
          ariaLabelForHandle={`${label} ${t("workbench.controls.slider", "滑块")}`}
          ariaValueTextFormatterForHandle={(next) =>
            sliderValue == null
              ? t("modelProfile.thinkingModeOption.default")
              : String(next)
          }
          onChange={(next) => {
            if (!isValid(next)) return;
            setText(String(next));
            setError(false);
            setDirty(true);
          }}
          onChangeComplete={(next) => {
            if (isValid(next)) onChange(next);
          }}
        />
        <input
          type="number"
          min={sliderMin}
          max={max}
          step={step}
          placeholder={t("modelProfile.thinkingModeOption.default")}
          aria-label={label}
          aria-invalid={invalid}
          disabled={disabled}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setDirty(true);
          }}
          onBlur={commit}
          onKeyDown={(event) => {
            event.stopPropagation();
            if (event.key === "Enter") {
              event.preventDefault();
              commit();
            }
          }}
          className="h-8 w-36 shrink-0 rounded border border-border px-2 text-sm"
        />
      </div>
      {invalid && (
        <p role="alert" className="text-xs text-destructive">
          {topP
            ? t("modelParams.topPInvalid")
            : t("workbench.controls.numberRange", {
                defaultValue: "请输入 {{min}}–{{max}} 的数字",
                min,
                max,
              })}
        </p>
      )}
    </div>
  );
}

/** Shared selector entry and nested panel for legacy and profile parameters. */
export function ModelParameterPopover({
  children,
  disabled,
  onOpenChange,
}: {
  children: ReactNode | ((close: () => void) => ReactNode);
  disabled?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const suppressHoverOpen = useRef(false);
  const changeOpen = useCallback(
    (next: boolean) => {
      setOpen(next);
      onOpenChange?.(next);
    },
    [onOpenChange]
  );
  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (
        event.target instanceof Element &&
        !event.target.closest(
          "[data-model-parameter-panel], [data-model-parameter-trigger], [data-model-effort-popup]"
        )
      )
        changeOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      suppressHoverOpen.current = true;
      changeOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape, true);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape, true);
    };
  }, [open, changeOpen]);
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (next && suppressHoverOpen.current) return;
        changeOpen(next);
      }}
      trigger={["hover", "click"]}
      placement="right"
      autoAdjustOverflow
      zIndex={1130}
      mouseEnterDelay={0.15}
      mouseLeaveDelay={0.25}
      content={
        <div
          data-model-parameter-panel
          role="region"
          aria-label={t("workbench.controls.advanced", "高级设置")}
          className="max-h-[calc(100dvh-48px)] w-64 max-w-[calc(100vw-48px)] space-y-3 overflow-y-auto"
          onKeyDown={(event) => {
            event.stopPropagation();
            if (event.key === "Escape") changeOpen(false);
          }}
        >
          {typeof children === "function"
            ? children(() => changeOpen(false))
            : children}
        </div>
      }
    >
      <button
        data-model-parameter-trigger
        type="button"
        disabled={disabled}
        aria-expanded={open}
        onPointerMove={() => {
          suppressHoverOpen.current = false;
        }}
        onClick={() => {
          suppressHoverOpen.current = open;
          changeOpen(!open);
        }}
        onKeyDown={(event) => {
          if (["Enter", "ArrowRight", " "].includes(event.key)) {
            event.preventDefault();
            event.stopPropagation();
            suppressHoverOpen.current = false;
            changeOpen(true);
          }
          if (event.key === "Escape") changeOpen(false);
        }}
        className="flex w-full items-center justify-between gap-3 border-b px-3 py-2 text-sm font-normal hover:bg-accent"
      >
        <span>{t("workbench.controls.advanced", "高级设置")}</span>
        <ChevronRight className="ml-auto size-4" />
      </button>
    </Popover>
  );
}

export function ModelSamplingFields(
  control: ModelParameterSettingsControl & {
    disabledFields?: string[];
    bounds?: Record<string, { min?: number; max?: number }>;
    schemas?: Partial<Record<SamplingField, Record<string, unknown>>>;
  }
) {
  const { t } = useTranslation();
  const [resetVersion, setResetVersion] = useState(0);
  return (
    <>
      <ParameterLevel
        key={`temperature-${resetVersion}`}
        label={t("workbench.controls.temperature", "温度")}
        value={control.value.temperature}
        inheritedValue={control.inheritedValue?.temperature}
        min={Math.max(0, control.bounds?.temperature?.min ?? 0)}
        max={Math.min(2, control.bounds?.temperature?.max ?? 2)}
        field="temperature"
        schema={control.schemas?.temperature}
        onClear={() => {
          const next = { ...control.value };
          delete next.temperature;
          control.onChange(next);
        }}
        disabled={
          control.disabled || control.disabledFields?.includes("temperature")
        }
        onChange={(temperature) =>
          control.onChange({ ...control.value, temperature })
        }
      />
      <ParameterLevel
        key={`top-p-${resetVersion}`}
        label="Top P"
        value={control.value.top_p}
        inheritedValue={control.inheritedValue?.top_p}
        min={control.bounds?.top_p?.min}
        max={Math.min(control.bounds?.top_p?.max ?? 1, 1)}
        field="top_p"
        schema={control.schemas?.top_p}
        onClear={() => {
          const next = { ...control.value };
          delete next.top_p;
          control.onChange(next);
        }}
        disabled={control.disabled || control.disabledFields?.includes("top_p")}
        onChange={(top_p) => control.onChange({ ...control.value, top_p })}
      />
      {(configuredValue(
        control.value.temperature ?? control.inheritedValue?.temperature,
        2
      ) == null ||
        configuredValue(
          control.value.top_p ?? control.inheritedValue?.top_p,
          1
        ) == null) && (
        <p className="text-xs text-muted-foreground">
          {t(
            "workbench.controls.configureDefaults",
            "请先在模型配置中设置默认值，或输入本次使用的数值。"
          )}
        </p>
      )}
      <Button
        size="small"
        htmlType="button"
        disabled={control.disabled}
        onPointerDown={(event) => event.preventDefault()}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          control.onChange({ ...control.defaultValue });
          setResetVersion((value) => value + 1);
        }}
      >
        {t("workbench.controls.restore", "恢复默认")}
      </Button>
    </>
  );
}

export function ModelParameterSettings(control: ModelParameterSettingsControl) {
  return (
    <ModelParameterPopover disabled={control.disabled}>
      <ModelSamplingFields {...control} />
    </ModelParameterPopover>
  );
}
