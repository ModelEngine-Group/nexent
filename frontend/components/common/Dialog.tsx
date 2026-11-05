// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";
import type { ComponentProps } from "react";
import { Dialog as Primitive } from "radix-ui";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { DialogPortal, DialogOverlay } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
export * from "@/components/ui/dialog";
export function DialogContent({
  className,
  children,
  showCloseButton = true,
  overlayClassName,
  forceMount,
  ...props
}: ComponentProps<typeof Primitive.Content> & {
  showCloseButton?: boolean;
  overlayClassName?: string;
}) {
  const { t } = useTranslation("common");
  return (
    <DialogPortal forceMount={forceMount}>
      <DialogOverlay
        className={cn("z-[var(--ui-layer-modal)]", overlayClassName)}
      />
      <Primitive.Content
        forceMount={forceMount}
        data-slot="dialog-content"
        className={cn(
          "fixed top-1/2 left-1/2 z-[var(--ui-layer-modal)] -translate-x-1/2 -translate-y-1/2 w-full max-w-[calc(100%-2rem)] rounded-lg border bg-background p-6 shadow-lg outline-none",
          className
        )}
        {...props}
      >
        {children}
        {showCloseButton && (
          <Primitive.Close
            aria-label={t("common.close")}
            className="absolute right-4 top-4 rounded-sm opacity-70 hover:opacity-100 focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="size-4" />
          </Primitive.Close>
        )}
      </Primitive.Content>
    </DialogPortal>
  );
}
