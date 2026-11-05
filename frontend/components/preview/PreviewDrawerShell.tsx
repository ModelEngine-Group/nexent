// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Activity, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/common/Button";
import { Sheet, SheetTitle } from "@/components/ui/sheet";
import { Dialog as Primitive } from "radix-ui";
import { cn } from "@/lib/utils";

export interface PreviewDrawerShellProps {
  open: boolean;
  title: ReactNode;
  closeLabel: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  extra?: ReactNode;
  width?: number | string;
  className?: string;
  bodyClassName?: string;
  maskClosable?: boolean;
}

export function PreviewDrawerShell({
  open,
  title,
  closeLabel,
  onClose,
  children,
  footer,
  extra,
  width = 560,
  className,
  bodyClassName,
  maskClosable = false,
}: PreviewDrawerShellProps) {
  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <Activity mode={open ? "visible" : "hidden"}>
        <Primitive.Portal forceMount>
          <Primitive.Overlay className="fixed inset-0 z-[var(--ui-layer-modal)] bg-black/50" />
          <Primitive.Content
            forceMount
            aria-describedby={undefined}
            data-ui-layer=""
            className={cn(
              "fixed inset-y-0 right-0 z-[var(--ui-layer-modal)] flex h-dvh flex-col gap-0 border-l bg-background p-0 shadow-lg outline-none data-[state=open]:animate-in data-[state=open]:slide-in-from-right",
              className
            )}
            style={{ width, maxWidth: "100vw" }}
            onInteractOutside={(event) => {
              if (!maskClosable) event.preventDefault();
            }}
          >
            <div className="flex shrink-0 items-center gap-3 border-b px-4 py-3">
              <SheetTitle className="min-w-0 flex-1">{title}</SheetTitle>
              {extra}
              <Button
                variant="ghost"
                size="icon"
                className="size-8 shrink-0"
                aria-label={closeLabel}
                onClick={onClose}
              >
                <X className="size-4" />
              </Button>
            </div>
            <div
              className={cn("min-h-0 flex-1 overflow-auto p-4", bodyClassName)}
            >
              {children}
            </div>
            {footer != null && (
              <div className="flex shrink-0 justify-end gap-2 border-t p-4">
                {footer}
              </div>
            )}
          </Primitive.Content>
        </Primitive.Portal>
      </Activity>
    </Sheet>
  );
}
