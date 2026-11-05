// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  forwardRef,
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentProps,
} from "react";
import { Textarea as BaseTextarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

export interface TextareaProps extends ComponentProps<typeof BaseTextarea> {
  minRows?: number;
  maxRows?: number;
  showCount?: boolean;
  countLimit?: number;
  countClassName?: string;
}

/** Native textarea events with optional bounded autosizing and a character counter. */
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  function Textarea(
    {
      minRows,
      maxRows,
      rows,
      showCount,
      countLimit,
      countClassName,
      value,
      defaultValue,
      maxLength,
      onChange,
      className,
      style,
      ...props
    },
    forwardedRef
  ) {
    const input = useRef<HTMLTextAreaElement | null>(null);
    const [localValue, setLocalValue] = useState(defaultValue ?? "");
    const resize = useCallback(() => {
      const element = input.current;
      if (!element || minRows === undefined) return;
      const computed = getComputedStyle(element);
      const lineHeight =
        parseFloat(computed.lineHeight) || parseFloat(computed.fontSize) * 1.5;
      const padding =
        parseFloat(computed.paddingTop) + parseFloat(computed.paddingBottom);
      const border =
        parseFloat(computed.borderTopWidth) +
        parseFloat(computed.borderBottomWidth);
      const minimum = minRows * lineHeight + padding + border;
      const maximum =
        maxRows === undefined
          ? Infinity
          : maxRows * lineHeight + padding + border;
      element.style.height = "0px";
      const height = Math.min(
        maximum,
        Math.max(minimum, element.scrollHeight + border)
      );
      element.style.height = `${height}px`;
      element.style.overflowY =
        element.scrollHeight + border > maximum ? "auto" : "hidden";
    }, [minRows, maxRows]);
    useLayoutEffect(() => {
      resize();
    }, [resize, value, localValue]);
    useLayoutEffect(() => {
      const element = input.current;
      if (!element || minRows === undefined) return;
      let width = element.clientWidth;
      const observer = new ResizeObserver(() => {
        if (element.clientWidth !== width) {
          width = element.clientWidth;
          resize();
        }
      });
      observer.observe(element);
      return () => observer.disconnect();
    }, [resize, minRows]);
    const limit = countLimit ?? maxLength;
    const field = (
      <BaseTextarea
        {...props}
        ref={(element) => {
          input.current = element;
          if (typeof forwardedRef === "function") forwardedRef(element);
          else if (forwardedRef) forwardedRef.current = element;
        }}
        rows={rows ?? minRows}
        value={value}
        defaultValue={defaultValue}
        maxLength={maxLength}
        style={style}
        className={cn(
          (rows !== undefined || minRows !== undefined) && "field-sizing-fixed",
          minRows !== undefined && "min-h-0",
          className
        )}
        onChange={(event) => {
          setLocalValue(event.target.value);
          onChange?.(event);
        }}
      />
    );
    if (!showCount) return field;
    return (
      <div className="relative min-w-0 w-full">
        {field}
        <div
          aria-live="off"
          className={cn(
            "mt-1 text-right text-xs text-muted-foreground tabular-nums",
            countClassName
          )}
        >
          {String(value ?? localValue).length}
          {limit !== undefined && `/${limit}`}
        </div>
      </div>
    );
  }
);
