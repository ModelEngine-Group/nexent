// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Button, Popover } from "antd";
import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ModelParameterSettingsControl } from "@/types/modelParameterSettings";

import {
  validSampling,
  type SamplingField,
} from "@/lib/modelSamplingParameters";
import { SamplingInput } from "@/components/model/SamplingInput";

function ParameterLevel({
  label,
  value,
  inheritedValue,
  disabled,
  field,
  schema,
  onClear,
  onChange,
}: {
  label: string;
  value?: number;
  inheritedValue?: number;
  disabled?: boolean;
  field: SamplingField;
  schema?: Record<string, unknown>;
  onClear: () => void;
  onChange: (value: number) => void;
}) {
  const displayValue = value ?? inheritedValue;
  const [draft, setDraft] = useState(displayValue ?? null);
  const [previousValue, setPreviousValue] = useState(displayValue);
  if (previousValue !== displayValue) {
    setPreviousValue(displayValue);
    setDraft(displayValue ?? null);
  }
  const commit = (next: number | null) => {
    if (next === null) {
      setDraft(inheritedValue ?? null);
      if (value !== undefined) onClear();
    } else if (validSampling(field, next, schema) && next !== value) {
      onChange(next);
    }
  };
  return (
    <div className="space-y-1">
      <label className="text-sm">{label}</label>
      <SamplingInput
        field={field}
        label={label}
        value={draft}
        schema={schema}
        disabled={disabled}
        showAllowedRange
        onChange={setDraft}
        onCommit={commit}
      />
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
          className="max-h-[calc(100dvh-48px)] w-52 max-w-[calc(100vw-48px)] space-y-3 overflow-y-auto"
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
      <p className="text-xs text-muted-foreground">
        {t("modelParams.samplingInheritanceHint")}
      </p>
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
