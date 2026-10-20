// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Button, Modal, Tooltip } from "antd";
import { Input as AntInput, type InputProps } from "antd";
import { RotateCw } from "lucide-react";
import {
  forwardRef,
  type HTMLAttributes,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";

import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { StandardCloseButton } from "@/components/common/StandardCloseButton";
import styles from "./ParamDialog.module.css";

/** Centered 480px parameter-config dialog (slides in the middle of the page). */
export function ParamDialog({
  open,
  title,
  description,
  onClose,
  onConfirm,
  confirmText,
  cancelText,
  zIndex,
  maskClosable = false,
  confirmDisabled = false,
  confirmLoading = false,
  onReset,
  resetText,
  resetDisabled = false,
  cancelDisabled = false,
  destroyOnHidden = false,
  footer,
  children,
  variant,
}: {
  variant?: "skill" | "tool" | "model" | "publish";
  open: boolean;
  title: ReactNode;
  description?: ReactNode;
  onClose: () => void;
  onConfirm?: () => void;
  confirmText?: string;
  cancelText?: string;
  zIndex?: number;
  maskClosable?: boolean;
  confirmDisabled?: boolean;
  confirmLoading?: boolean;
  onReset?: () => void;
  resetText?: string;
  resetDisabled?: boolean;
  cancelDisabled?: boolean;
  destroyOnHidden?: boolean;
  /** Replace the default footer; pass null to let the body render its own. */
  footer?: ReactNode | null;
  children: ReactNode;
}) {
  const { t } = useTranslation("common");
  return (
    <Modal
      open={open}
      onCancel={onClose}
      centered
      width={480}
      footer={null}
      closable={false}
      zIndex={zIndex}
      maskClosable={maskClosable}
      destroyOnHidden={destroyOnHidden}
      styles={{
        container: {
          padding: 0,
          borderRadius: 8,
          boxShadow: "0 0 15px rgba(26,26,26,0.1)",
        },
        body: { padding: 0 },
      }}
    >
      <div className={styles.dialog} data-config-variant={variant}>
        <div
          data-config-part="heading"
          className="flex shrink-0 flex-col gap-2"
        >
          <div
            data-config-part="header"
            className="flex h-6 shrink-0 items-center justify-between gap-4"
          >
            <span className="min-w-0 text-[16px] font-bold leading-6 text-[#1A1A1A]">
              {title}
            </span>
            <StandardCloseButton
              ariaLabel={t("common.close")}
              onClick={onClose}
            />
          </div>
          {description ? (
            <div
              data-config-part="description"
              className="text-[12px] leading-[18px] text-[#191919]/40"
            >
              {description}
            </div>
          ) : null}
        </div>
        <div data-config-part="body" className={styles.body}>
          {children}
        </div>
        {footer === undefined ? (
          <div
            data-config-part="footer"
            className="flex h-8 shrink-0 justify-end gap-4"
          >
            {onReset ? (
              <button
                type="button"
                className={styles.resetLink}
                disabled={resetDisabled}
                onClick={onReset}
              >
                {resetText ?? t("common.reset")}
              </button>
            ) : null}
            <Button
              autoInsertSpace={false}
              onClick={onClose}
              disabled={cancelDisabled}
              className={styles.cancelButton}
            >
              {cancelText ?? t("common.cancel")}
            </Button>
            {onConfirm && (
              <Button
                autoInsertSpace={false}
                onClick={onConfirm}
                disabled={confirmDisabled}
                loading={confirmLoading}
                className={styles.confirmButton}
              >
                {confirmText ?? t("common.confirm")}
              </Button>
            )}
          </div>
        ) : (
          footer
        )}
      </div>
    </Modal>
  );
}

/** 38x20 toggle switch with a 16px knob. */
export function ParamSwitch({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative h-5 w-[38px] shrink-0 cursor-pointer rounded-[10px] border-0 transition-colors",
        checked ? "bg-[#0067D1]" : "bg-[#CCC]"
      )}
    >
      <span
        className={cn(
          "absolute top-[2px] h-4 w-4 rounded-full bg-white transition-all",
          checked ? "right-[2px]" : "left-[2px]"
        )}
      />
    </button>
  );
}

/** 4px track slider with fill + 12px knob and min/max labels. */
export function ParamSlider({
  value,
  minLabel,
  maxLabel,
  onChange,
}: {
  value: number;
  minLabel: string;
  maxLabel: string;
  onChange?: (value: number) => void;
}) {
  const handleTrackClick = (e: MouseEvent<HTMLDivElement>) => {
    if (!onChange) return;
    const rect = e.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;
    const pct = Math.round(((e.clientX - rect.left) / rect.width) * 100);
    onChange(Math.max(0, Math.min(100, pct)));
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!onChange) return;
    let nextValue: number;
    switch (event.key) {
      case "ArrowRight":
      case "ArrowUp":
        nextValue = value + 1;
        break;
      case "ArrowLeft":
      case "ArrowDown":
        nextValue = value - 1;
        break;
      case "Home":
        nextValue = 0;
        break;
      case "End":
        nextValue = 100;
        break;
      default:
        return;
    }
    event.preventDefault();
    onChange(Math.max(0, Math.min(100, nextValue)));
  };

  return (
    <div className="flex items-center gap-3">
      <div
        className="relative h-1 flex-1 cursor-pointer rounded-[2px] bg-[#E5E5E5]"
        role="slider"
        tabIndex={onChange ? 0 : -1}
        aria-label={`${minLabel} — ${maxLabel}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value}
        aria-disabled={!onChange}
        onClick={handleTrackClick}
        onKeyDown={handleKeyDown}
      >
        <div
          className="absolute left-0 top-0 h-1 rounded-[2px] bg-[#0567D1]"
          style={{ width: `${value}%` }}
        />
        <div
          className="absolute top-1/2 h-3 w-3 -translate-y-1/2 rounded-full border-2 border-[#0567D1] bg-white"
          style={{ left: `calc(${value}% - 6px)` }}
        />
      </div>
      <span className="shrink-0 text-[12px] text-[#999]">
        {minLabel} — {maxLabel}
      </span>
    </div>
  );
}

/** Rounded "?" help icon used beside field labels. */
export const InfoIcon = forwardRef<
  HTMLSpanElement,
  { size?: number } & HTMLAttributes<HTMLSpanElement>
>(function InfoIcon({ size = 12, ...rest }, ref) {
  return (
    <span
      ref={ref}
      {...rest}
      className="inline-flex shrink-0 items-center justify-center rounded-full border border-[#CCC] font-normal not-italic text-[#BBB]"
      style={{ width: size, height: size, fontSize: size - 2 }}
    >
      ?
    </span>
  );
});

/** Ant Design input aligned to the 28px configuration control. */
export function ParamInput({
  inputSize = "md",
  className,
  ...props
}: InputProps & { inputSize?: "sm" | "md" }) {
  return (
    <AntInput
      {...props}
      data-input-size={inputSize}
      className={cn(
        "!w-full !rounded-[2px] !border-solid !h-7 !px-3 !text-[14px] !leading-[22px] !border-[#C9C9C9]",
        className
      )}
    />
  );
}

/** Field label with optional required mark, info icon, or custom icon. */
export function ParamLabel({
  label,
  required,
  info,
  infoText,
  icon,
  size = "sm",
}: {
  label: string;
  required?: boolean;
  info?: boolean;
  infoText?: string;
  icon?: ReactNode;
  size?: "sm" | "md";
}) {
  const showInfo = info && !icon;
  const infoNode = icon ?? (showInfo && <InfoIcon size={14} />);
  return (
    <span
      data-config-label
      className="relative flex items-center gap-1 text-[14px] leading-[22px] text-[#191919]"
    >
      {required && (
        <span
          data-config-required
          className={size === "md" ? "text-[#E34D59]" : "text-[#E33]"}
        >
          *
        </span>
      )}
      {label}
      {infoNode &&
        (showInfo && infoText ? (
          <Tooltip title={infoText}>{infoNode}</Tooltip>
        ) : (
          infoNode
        ))}
    </span>
  );
}

/** Ordered field with an 8px gap between its label and control. */
export function ParamField({
  label,
  required,
  info,
  infoText,
  icon,
  size = "sm",
  children,
}: {
  label: string;
  required?: boolean;
  info?: boolean;
  infoText?: string;
  icon?: ReactNode;
  size?: "sm" | "md";
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <ParamLabel
        label={label}
        required={required}
        info={info}
        infoText={infoText}
        icon={icon}
        size={size}
      />
      {children}
    </div>
  );
}

/** Fixed chevron geometry avoids font-dependent section arrow shapes. */
export function SectionChevron({ expanded }: { expanded: boolean }) {
  return (
    <svg
      aria-hidden="true"
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      className="shrink-0 text-[#666]"
    >
      <path
        d={expanded ? "M2 8L6 4L10 8" : "M2 4L6 8L10 4"}
        stroke="currentColor"
        strokeWidth="1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Collapsible section header with expand/collapse arrow. */
export function SectionHeader({
  title,
  expanded,
  onToggle,
}: {
  title: string;
  expanded: boolean;
  onToggle?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex h-6 items-center gap-1.5 border-0 bg-transparent p-0 text-[14px] font-bold leading-6 text-[#191919]"
    >
      {title}
      <SectionChevron expanded={expanded} />
    </button>
  );
}

/** "点击测试" run-test link with circular arrow. */
export function TestRunLink({
  label = "点击测试",
  onClick,
  disabled = false,
}: {
  label?: string;
  onClick?: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      data-config-part="test-run"
      onClick={onClick}
      disabled={disabled}
      className="flex h-[22px] cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-[14px] leading-[22px] text-[#2673E5] disabled:cursor-not-allowed disabled:opacity-50"
    >
      <RotateCw size={16} />
      {label}
    </button>
  );
}

/** Test result placeholder area (99px). */
export function TestResultArea() {
  return <div className="h-[99px] w-full rounded-[4px] bg-[#EFEFEF]" />;
}
