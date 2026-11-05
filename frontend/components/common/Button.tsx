// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";
import type { ComponentProps, ReactNode } from "react";
import { LoaderCircle } from "lucide-react";
import {
  Button as BaseButton,
  buttonVariants as baseButtonVariants,
} from "@/components/ui/button";
import { cn } from "@/lib/utils";
export type ButtonProps = ComponentProps<typeof BaseButton> & {
  loading?: boolean;
  icon?: ReactNode;
  href?: string;
};
export function buttonVariants(
  options: Parameters<typeof baseButtonVariants>[0] = {}
) {
  return cn(
    baseButtonVariants(options),
    "cursor-pointer tracking-normal",
    (!options.size || options.size === "default") && "h-10",
    options.variant === "link" &&
      "hover:text-primary-hover active:text-primary-active",
    (!options.variant || options.variant === "default") &&
      "hover:bg-primary-hover active:bg-primary-active disabled:bg-primary-disabled disabled:opacity-100 aria-disabled:bg-primary-disabled aria-disabled:opacity-100"
  );
}
/** Project dimensions, safe native defaults and caller-owned pending state. */
export function Button({
  type = "button",
  variant = "default",
  size = "default",
  loading = false,
  disabled,
  icon,
  children,
  className,
  asChild,
  href,

  ...props
}: ButtonProps) {
  const content = (
    <>
      {loading ? (
        <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
      ) : (
        icon
      )}
      {children}
    </>
  );
  const classes = cn(buttonVariants({ variant, size }), className);
  if (href !== undefined) {
    return (
      <BaseButton
        {...props}
        asChild
        variant={variant}
        size={size}
        className={classes}
        aria-busy={loading || undefined}
        onClick={(event) => {
          if (disabled || loading) {
            event.preventDefault();
            return;
          }
          props.onClick?.(event);
        }}
      >
        <a
          href={disabled || loading ? undefined : href}
          aria-disabled={disabled || loading || undefined}
          tabIndex={disabled || loading ? -1 : undefined}
        >
          {content}
        </a>
      </BaseButton>
    );
  }
  return (
    <BaseButton
      {...props}
      asChild={asChild}
      type={asChild ? undefined : type}
      variant={variant}
      size={size}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
    >
      {asChild ? children : content}
    </BaseButton>
  );
}
