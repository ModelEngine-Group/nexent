// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  forwardRef,
  useImperativeHandle,
  useRef,
  useState,
  type InputHTMLAttributes,
  type KeyboardEventHandler,
  type ReactNode,
} from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface InputFieldProps extends Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "prefix" | "size"
> {
  prefix?: ReactNode;
  suffix?: ReactNode;
  allowClear?: boolean;
  onPressEnter?: KeyboardEventHandler<HTMLInputElement>;
  showCount?: boolean;
  countLimit?: number;
  countStrategy?: (value: string) => number;
}

/** Adornments and clearing are shared behavior; plain fields use ui/Input directly. */
export const InputField = forwardRef<HTMLInputElement, InputFieldProps>(
  function InputField(
    {
      prefix,
      suffix,
      allowClear = false,
      showCount = false,
      countLimit,
      countStrategy = (text) => text.length,
      onPressEnter,
      onKeyDown,
      onChange,
      className,
      style,
      disabled,
      readOnly,
      value,
      defaultValue,
      ...props
    },
    forwardedRef
  ) {
    const { t } = useTranslation("common");
    const input = useRef<HTMLInputElement>(null);
    useImperativeHandle(forwardedRef, () => input.current!);
    const [localValue, setLocalValue] = useState(defaultValue ?? "");
    const displayed = value ?? localValue;
    const adorned = prefix || suffix || allowClear || showCount;
    const clear = () => {
      if (!input.current || disabled || readOnly) return;
      // Use the native setter so React observes a genuine input event and Form
      // consumers keep their normal onChange contract, including uncontrolled input.
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value"
      )?.set?.call(input.current, "");
      input.current.dispatchEvent(new Event("input", { bubbles: true }));
      setLocalValue("");
      input.current.focus();
    };
    const field = (
      <Input
        {...props}
        ref={input}
        value={value}
        defaultValue={defaultValue}
        disabled={disabled}
        readOnly={readOnly}
        style={adorned ? undefined : style}
        className={cn(
          adorned &&
            "h-full min-w-0 flex-1 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0 focus-visible:ring-offset-0",
          !adorned && className
        )}
        onChange={(event) => {
          setLocalValue(event.target.value);
          onChange?.(event);
        }}
        onKeyDown={(event) => {
          onKeyDown?.(event);
          if (
            event.key === "Enter" &&
            !event.nativeEvent.isComposing &&
            !event.defaultPrevented
          )
            onPressEnter?.(event);
        }}
      />
    );
    if (!adorned) return field;
    return (
      <div
        style={style}
        className={cn(
          "flex h-9 w-full min-w-0 items-center gap-2 rounded-md border border-input bg-background px-3 focus-within:ring-2 focus-within:ring-ring has-[[aria-invalid=true]]:border-destructive",
          disabled && "opacity-50",
          className
        )}
      >
        {prefix && <span className="shrink-0">{prefix}</span>}
        {field}
        {allowClear &&
          !disabled &&
          !readOnly &&
          String(displayed).length > 0 && (
            <button
              type="button"
              className="rounded-sm text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label={t("common.clear")}
              onClick={clear}
            >
              <X className="size-3.5" />
            </button>
          )}
        {suffix && <span className="shrink-0">{suffix}</span>}
        {showCount && (
          <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
            {countStrategy(String(displayed))}
            {(countLimit ?? props.maxLength) !== undefined &&
              `/${countLimit ?? props.maxLength}`}
          </span>
        )}
      </div>
    );
  }
);
