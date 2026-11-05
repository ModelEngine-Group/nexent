// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { ComponentProps, MouseEventHandler } from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge as BaseBadge } from "@/components/ui/badge";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center justify-center gap-1 rounded-md text-xs font-medium transition-colors [&_svg]:size-3 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        outline:
          "border-input text-muted-foreground hover:bg-accent hover:text-accent-foreground border bg-transparent",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        muted:
          "bg-muted text-muted-foreground hover:bg-muted/80 hover:text-foreground",
        ghost:
          "text-muted-foreground hover:bg-accent hover:text-accent-foreground bg-transparent",
        info: "bg-brand-soft text-brand-soft-foreground hover:bg-primary/15",
        warning:
          "bg-amber-100 text-amber-700 hover:bg-amber-100/80 dark:bg-amber-900/50 dark:text-amber-300",
        success:
          "bg-emerald-100 text-emerald-700 hover:bg-emerald-100/80 dark:bg-emerald-900/50 dark:text-emerald-300",
        destructive:
          "bg-red-100 text-red-700 hover:bg-red-100/80 dark:bg-red-900/50 dark:text-red-300",
      },
      size: {
        sm: "px-1.5 py-0.5",
        default: "px-2 py-1",
        lg: "px-2.5 py-1.5 text-sm",
      },
    },
    defaultVariants: {
      variant: "outline",
      size: "default",
    },
  }
);

export type BadgeProps = ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & {
    asChild?: boolean;
    onRemove?: MouseEventHandler<HTMLButtonElement>;
  };

function Badge({
  className,
  variant,
  size,
  asChild = false,
  onRemove,
  children,
  ...props
}: BadgeProps) {
  const { t } = useTranslation("common");
  return (
    <BaseBadge
      variant="outline"
      asChild={asChild}
      data-slot="badge"
      data-variant={variant}
      data-size={size}
      className={cn(badgeVariants({ variant, size }), className)}
      {...props}
    >
      {onRemove ? (
        <>
          {children}
          <button
            type="button"
            aria-label={t("common.close")}
            className="ml-1 shrink-0 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={onRemove}
          >
            <X aria-hidden="true" className="size-3" />
          </button>
        </>
      ) : (
        children
      )}
    </BaseBadge>
  );
}

export { Badge, badgeVariants };
