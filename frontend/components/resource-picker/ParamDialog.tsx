"use client";

import { Modal } from "antd";
import { Input as AntInput, type InputProps } from "antd";
import { RotateCw, X } from "lucide-react";
import type { MouseEvent, ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Centered 480px parameter-config dialog (slides in the middle of the page). */
export function ParamDialog({
  open,
  title,
  onClose,
  onConfirm,
  confirmText = "确定",
  cancelText = "取消",
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  onConfirm?: () => void;
  confirmText?: string;
  cancelText?: string;
  children: ReactNode;
}) {
  return (
    <Modal
      open={open}
      onCancel={onClose}
      centered
      width={480}
      footer={null}
      closable={false}
      maskClosable={false}
      styles={{
        container: { padding: 0, borderRadius: 8, boxShadow: "0 8px 30px rgba(0,0,0,.12)" },
        body: { padding: 0 },
      }}
    >
      <div className="flex flex-col gap-3 p-6">
        <div className="flex items-center justify-between">
          <span className="text-[16px] font-bold leading-6 text-[#1A1A1A]">
            {title}
          </span>
          <button
            type="button"
            aria-label="close"
            onClick={onClose}
            className="flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center border-0 bg-transparent p-0 text-[#666]"
          >
            <X size={12} />
          </button>
        </div>
        {children}
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="h-8 w-[89px] rounded-[2px] border border-[#C9C9C9] bg-white text-[14px] text-[#191919]"
          >
            {cancelText}
          </button>
          {onConfirm && (
            <button
              type="button"
              onClick={onConfirm}
              className="h-8 w-[89px] rounded-[2px] border border-[#2673E5] bg-[#2673E5] text-[14px] text-white"
            >
              {confirmText}
            </button>
          )}
        </div>
      </div>
    </Modal>
  );
}

/** 58x28 toggle switch with a 22px knob (design spec). */
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
        "relative h-7 w-[58px] shrink-0 cursor-pointer rounded-[14px] border-0 transition-colors",
        checked ? "bg-[#0067D1]" : "bg-[#CCC]"
      )}
    >
      <span
        className={cn(
          "absolute top-[3px] h-[22px] w-[22px] rounded-full bg-white transition-all",
          checked ? "right-[3px]" : "left-[3px]"
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
    const pct = Math.round(((e.clientX - rect.left) / rect.width) * 100);
    onChange(Math.max(0, Math.min(100, pct)));
  };

  return (
    <div className="flex items-center gap-3">
      <div
        className="relative h-1 flex-1 cursor-pointer rounded-[2px] bg-[#E5E5E5]"
        onClick={handleTrackClick}
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

/** Rounded "i" info icon used beside field labels. */
export function InfoIcon({ size = 12 }: { size?: number }) {
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full border border-[#CCC] font-normal not-italic text-[#BBB]"
      style={{ width: size, height: size, fontSize: size - 2 }}
    >
      i
    </span>
  );
}

/** antd Input restyled to the design's 26px ("sm") / 28px ("md") variants. */
export function ParamInput({
  inputSize = "md",
  className,
  ...props
}: InputProps & { inputSize?: "sm" | "md" }) {
  return (
    <AntInput
      {...props}
      className={cn(
        "!w-full !rounded-[2px] !border-solid",
        inputSize === "sm"
          ? "!h-[26px] !px-2 !text-[13px] !border-[#D9D9D9]"
          : "!h-7 !px-3 !text-[14px] !border-[#D9D9D9]",
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
  icon,
  size = "sm",
}: {
  label: string;
  required?: boolean;
  info?: boolean;
  icon?: ReactNode;
  size?: "sm" | "md";
}) {
  return (
    <span
      className={cn(
        "flex items-center gap-1",
        size === "md"
          ? "text-[14px] leading-[22px] text-[#191919]"
          : "text-[12px] leading-[18px] text-[#393939]"
      )}
    >
      {required && (
        <span className={size === "md" ? "text-[#E34D59]" : "text-[#E33]"}>
          *
        </span>
      )}
      {label}
      {icon ?? (info && <InfoIcon size={size === "md" ? 14 : 12} />)}
    </span>
  );
}

/** Ordered field (label above control), with design gap based on label size. */
export function ParamField({
  label,
  required,
  info,
  icon,
  size = "sm",
  children,
}: {
  label: string;
  required?: boolean;
  info?: boolean;
  icon?: ReactNode;
  size?: "sm" | "md";
  children: ReactNode;
}) {
  return (
    <div className={cn("flex flex-col", size === "md" ? "gap-2" : "gap-1.5")}>
      <ParamLabel
        label={label}
        required={required}
        info={info}
        icon={icon}
        size={size}
      />
      {children}
    </div>
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
      <span className="text-[12px] font-normal text-[#666]">
        {expanded ? "∧" : "∨"}
      </span>
    </button>
  );
}

/** "点击测试" run-test link with circular arrow. */
export function TestRunLink({
  label = "点击测试",
  onClick,
}: {
  label?: string;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex h-6 cursor-pointer items-center gap-1.5 border-0 bg-transparent p-0 text-[14px] text-[#2673E5]"
    >
      <RotateCw size={14} />
      {label}
    </button>
  );
}

/** Test result placeholder area (99px). */
export function TestResultArea() {
  return <div className="h-[99px] w-full rounded-[4px] bg-[#EFEFEF]" />;
}