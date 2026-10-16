"use client";

import { useEffect, useState } from "react";
import { Button, Popover, Slider } from "antd";
import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ModelParameterSettingsControl } from "@/types/modelParameterSettings";

function ParameterLevel({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: number;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState(String(value));
  const [error, setError] = useState(false);
  const [previousValue, setPreviousValue] = useState(value);
  if (previousValue !== value) {
    setPreviousValue(value);
    setText(String(value));
    setError(false);
  }
  const commit = () => {
    const next = Number(text);
    if (!text.trim() || !Number.isInteger(next) || next < 1 || next > 100) {
      setError(true);
      return;
    }
    setError(false);
    if (next !== value) onChange(next);
  };
  return (
    <div className="space-y-1">
      <label className="text-sm">{label}</label>
      <div className="flex items-center gap-3">
        <Slider
          min={1}
          max={100}
          step={1}
          value={
            Number(text) >= 1 && Number(text) <= 100 ? Number(text) : value
          }
          disabled={disabled}
          className="min-w-0 flex-1"
          ariaLabelForHandle={`${label} ${t("workbench.controls.slider", "滑块")}`}
          onChange={(next) => {
            setText(String(next));
            setError(false);
          }}
          onChangeComplete={onChange}
        />
        <input
          type="number"
          min={1}
          max={100}
          step={1}
          aria-label={label}
          aria-invalid={error}
          disabled={disabled}
          value={text}
          onChange={(event) => setText(event.target.value)}
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
          {t("workbench.controls.integerRange", "请输入 1–100 的整数")}
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
            value={control.value.temperatureLevel}
            disabled={control.disabled}
            onChange={(temperatureLevel) =>
              control.onChange({ ...control.value, temperatureLevel })
            }
          />
          <ParameterLevel
            key={`top-p-${resetVersion}`}
            label="Top P"
            value={control.value.topPLevel}
            disabled={control.disabled}
            onChange={(topPLevel) =>
              control.onChange({ ...control.value, topPLevel })
            }
          />
          <Button
            size="small"
            disabled={control.disabled}
            onClick={() => {
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
        onFocus={() => setOpen(true)}
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
