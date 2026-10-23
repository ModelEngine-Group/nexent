// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useState } from "react";
import { Button, Popover, Slider } from "antd";
import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ModelParameterSettingsControl } from "@/types/modelParameterSettings";

function configuredValue(value: number | undefined, max: number) {
  return value != null && Number.isFinite(value) && value >= 0 && value <= max
    ? value
    : undefined;
}

function ParameterLevel({
  label,
  value,
  inheritedValue,
  max,
  disabled,
  onChange,
}: {
  label: string;
  value?: number;
  inheritedValue?: number;
  max: number;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  const { t } = useTranslation();
  const displayValue = configuredValue(value ?? inheritedValue, max);
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
    const next = Number(text);
    if (!text.trim() || !Number.isFinite(next) || next < 0 || next > max) {
      setError(true);
      return;
    }
    setError(false);
    setDirty(false);
    setText(String(next));
    if (next !== value) onChange(next);
  };
  const sliderValue = text.trim()
    ? (configuredValue(Number(text), max) ?? displayValue ?? null)
    : (displayValue ?? null);
  return (
    <div className="space-y-1">
      <label className="text-sm">{label}</label>
      <div className="flex items-center gap-3">
        {sliderValue != null ? (
          <Slider
            min={0}
            max={max}
            step={0.1}
            value={sliderValue}
            marks={{
              [sliderValue]: { label: <span />, style: { display: "none" } },
            }}
            disabled={disabled}
            className="!m-0 min-w-0 flex-1 [&_.ant-slider-dot]:hidden"
            ariaLabelForHandle={`${label} ${t("workbench.controls.slider", "滑块")}`}
            onChange={(next) => {
              setText(String(next));
              setError(false);
              setDirty(true);
            }}
            onChangeComplete={onChange}
          />
        ) : (
          <div
            aria-hidden="true"
            className="h-1 min-w-0 flex-1 rounded bg-muted"
          />
        )}
        <input
          type="number"
          min={0}
          max={max}
          step={0.1}
          placeholder="—"
          aria-label={label}
          aria-invalid={error}
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
          className="h-8 w-16 rounded border border-border px-2 text-sm"
        />
      </div>
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {t("workbench.controls.numberRange", {
            defaultValue: "请输入 {{min}}–{{max}} 的数字",
            min: 0,
            max,
          })}
        </p>
      )}
    </div>
  );
}

export function ModelParameterSettings(control: ModelParameterSettingsControl) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [resetVersion, setResetVersion] = useState(0);
  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (
        event.target instanceof Element &&
        !event.target.closest(
          "[data-model-parameter-panel], [data-model-parameter-trigger]"
        )
      )
        setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [open]);
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (
          !next &&
          document.activeElement?.closest("[data-model-parameter-panel]")
        )
          return;
        setOpen(next);
      }}
      trigger={["hover", "click"]}
      placement="rightTop"
      zIndex={1130}
      mouseEnterDelay={0.15}
      mouseLeaveDelay={0.25}
      content={
        <div
          data-model-parameter-panel
          role="region"
          aria-label={t("workbench.controls.advanced", "高级设置")}
          className="w-64 space-y-3"
          onKeyDown={(event) => {
            event.stopPropagation();
            if (event.key === "Escape") setOpen(false);
          }}
        >
          <ParameterLevel
            key={`temperature-${resetVersion}`}
            label={t("workbench.controls.temperature", "温度")}
            value={control.value.temperature}
            inheritedValue={control.inheritedValue?.temperature}
            max={2}
            disabled={control.disabled}
            onChange={(temperature) =>
              control.onChange({ ...control.value, temperature })
            }
          />
          <ParameterLevel
            key={`top-p-${resetVersion}`}
            label="Top P"
            value={control.value.top_p}
            inheritedValue={control.inheritedValue?.top_p}
            max={1}
            disabled={control.disabled}
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
        </div>
      }
    >
      <button
        data-model-parameter-trigger
        type="button"
        disabled={control.disabled}
        aria-expanded={open}
        onKeyDown={(event) => {
          if (["Enter", "ArrowRight", " "].includes(event.key)) {
            event.preventDefault();
            event.stopPropagation();
            setOpen(true);
          }
          if (event.key === "Escape") setOpen(false);
        }}
        className="flex w-full items-center justify-between gap-3 border-b px-3 py-2 text-sm font-normal hover:bg-accent"
      >
        <span>{t("workbench.controls.advanced", "高级设置")}</span>
        <ChevronRight className="ml-auto size-4" />
      </button>
    </Popover>
  );
}
