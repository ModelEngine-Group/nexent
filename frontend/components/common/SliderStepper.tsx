// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useRef, useState } from "react";
import { Minus, Plus } from "lucide-react";

const clamp = (value: number, min: number, max: number): number =>
  Math.min(max, Math.max(min, value));

const roundStep = (value: number, step: number): number => {
  const decimals = (String(step).split(".")[1] ?? "").length;
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
};

interface SliderStepperProps {
  label: string;
  value: number | undefined;
  fallback: number;
  min: number;
  max: number;
  step: number;
  disabled?: boolean;
  compact?: boolean;
  showFallbackValue?: boolean;
  onChange: (next: number | undefined) => void;
}

// Five segments -> only the four interior dividers (no ticks at either end).
const TICK_POSITIONS = [20, 40, 60, 80];

export function SliderStepper({
  label,
  value,
  fallback,
  min,
  max,
  step,
  disabled = false,
  compact = false,
  showFallbackValue = true,
  onChange,
}: SliderStepperProps) {
  const display = value ?? fallback;
  const hasDisplayValue = value !== undefined || showFallbackValue;
  const trackRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);

  const range = max - min || 1;
  const pct = clamp(((display - min) / range) * 100, 0, 100);

  const set = (next: number) => {
    if (disabled || !Number.isFinite(next)) return;
    onChange(roundStep(clamp(next, min, max), step));
  };

  const valueFromClientX = (clientX: number) => {
    const el = trackRef.current;
    if (!el) return display;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0) return display;
    const ratio = clamp((clientX - rect.left) / rect.width, 0, 1);
    return roundStep(min + ratio * range, step);
  };

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (disabled) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragging(true);
    set(valueFromClientX(e.clientX));
  };
  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    set(valueFromClientX(e.clientX));
  };
  const handlePointerUp = () => setDragging(false);

  return (
    <div className={`flex items-center ${compact ? "gap-2" : "gap-4"}`}>
      {/* Segmented slider */}
      <div className="flex-1 select-none">
        <div className="relative pt-2">
          {/* Four interior tick marks above the track */}
          <div className="pointer-events-none absolute inset-x-0 top-0 h-[6px]">
            {TICK_POSITIONS.map((pos) => (
              <span
                key={pos}
                className={`absolute top-0 h-[6px] w-[2px] -translate-x-1/2 rounded-full opacity-60 ${hasDisplayValue ? "bg-[#0067D1]" : "bg-[#E0E0E0]"}`}
                style={{ left: `${pos}%` }}
              />
            ))}
          </div>
          {/* Track */}
          <div
            ref={trackRef}
            role="slider"
            aria-label={label}
            aria-valuemin={min}
            aria-valuemax={max}
            aria-valuenow={hasDisplayValue ? display : undefined}
            aria-disabled={disabled}
            tabIndex={disabled ? -1 : 0}
            onKeyDown={(event) => {
              const keyValues: Record<string, number> = {
                ArrowRight: display + step,
                ArrowUp: display + step,
                ArrowLeft: display - step,
                ArrowDown: display - step,
                Home: min,
                End: max,
              };
              const next = keyValues[event.key];
              if (next === undefined || disabled) return;
              event.preventDefault();
              set(next);
            }}
            className="relative h-1 cursor-pointer touch-none rounded-full bg-[#E0E0E0]"
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerUp}
            onLostPointerCapture={handlePointerUp}
          >
            {hasDisplayValue && (
              <>
                <div
                  className="absolute left-0 top-0 h-full rounded-full bg-[#0067D1]"
                  style={{ width: `${pct}%` }}
                />
                <div
                  className="absolute top-1/2 flex h-6 w-6 -translate-x-1/2 -translate-y-1/2 items-center justify-center"
                  style={{ left: `clamp(12px, ${pct}%, calc(100% - 12px))` }}
                >
                  <span className="h-4 w-4 rounded-full border border-[#E0E0E0] bg-white shadow-[0_1px_3px_rgba(0,0,0,0.15)]" />
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Compact numeric controls leave more track space in two-column forms. */}
      <div
        className={`flex h-8 shrink-0 items-center justify-between rounded border border-[#E6E6E6] bg-white py-[5px] ${compact ? "w-[88px] px-1.5" : "w-[112px] px-2"} ${
          disabled ? "opacity-50" : ""
        }`}
      >
        <input
          type="number"
          aria-label={label}
          min={min}
          max={max}
          step={step}
          value={value ?? (showFallbackValue ? fallback : "")}
          disabled={disabled}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") {
              onChange(undefined);
            } else {
              set(Number(raw));
            }
          }}
          className="h-full min-w-0 flex-1 border-0 bg-transparent text-left text-[14px] leading-[22px] text-[#808080] outline-none"
        />
        <button
          type="button"
          aria-label={`${label} −`}
          onClick={() => set(display - step)}
          disabled={disabled}
          className={`flex h-5 shrink-0 items-center justify-center text-[#BDBDBD] disabled:cursor-not-allowed ${compact ? "w-4" : "w-5"}`}
        >
          <Minus size={12} />
        </button>
        <span className="mx-[3px] h-[14px] w-px shrink-0 bg-[#E6E6E6]" />
        <button
          type="button"
          aria-label={`${label} +`}
          onClick={() => set(display + step)}
          disabled={disabled}
          className={`flex h-5 shrink-0 items-center justify-center text-[#424242] disabled:cursor-not-allowed ${compact ? "w-4" : "w-5"}`}
        >
          <Plus size={12} />
        </button>
      </div>
    </div>
  );
}
