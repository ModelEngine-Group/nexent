// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Activity, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/common/Button";
import { Dialog, DialogContent, DialogTitle } from "@/components/common/Dialog";
import { cn } from "@/lib/utils";

export interface ModalProps {
  open: boolean;
  title: ReactNode;
  closeLabel: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  actions?: {
    cancelLabel: ReactNode;
    confirmLabel: ReactNode;
    onCancel?: () => void;
    onConfirm: () => void;
  };
  width?: number | string;
  height?: number | string;
  maxHeight?: number | string;
  closeOnEscape?: boolean;
  maskClosable?: boolean;
  className?: string;
  bodyClassName?: string;
}

/** Shared content/close contract; workflows and requests stay outside the shell. */
export function Modal({
  open,
  title,
  closeLabel,
  onClose,
  children,
  footer: customFooter,
  actions,
  width = 480,
  height,
  maxHeight,
  closeOnEscape = true,
  maskClosable = false,
  className,
  bodyClassName,
}: ModalProps) {
  const footer =
    customFooter === undefined && actions ? (
      <>
        <Button variant="outline" onClick={actions.onCancel ?? onClose}>
          {actions.cancelLabel}
        </Button>
        <Button onClick={actions.onConfirm}>{actions.confirmLabel}</Button>
      </>
    ) : (
      customFooter
    );
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <Activity mode={open ? "visible" : "hidden"}>
        <DialogContent
          forceMount
          showCloseButton={false}
          aria-describedby={undefined}
          overlayClassName="z-[var(--ui-layer-modal)]"
          data-ui-layer=""
          className={cn(
            "z-[var(--ui-layer-modal)] flex max-h-[90dvh] flex-col gap-4",
            className
          )}
          style={{ width, height, maxHeight, maxWidth: "calc(100vw - 2rem)" }}
          onEscapeKeyDown={(event) => {
            if (!closeOnEscape) event.preventDefault();
          }}
          onInteractOutside={(event) => {
            if (!maskClosable) event.preventDefault();
          }}
        >
          <div className="flex shrink-0 items-start justify-between gap-4">
            <DialogTitle>{title}</DialogTitle>
            <Button
              variant="ghost"
              size="icon"
              className="-mr-2 -mt-2 size-8 shrink-0"
              aria-label={closeLabel}
              onClick={onClose}
            >
              <X className="size-4" />
            </Button>
          </div>
          <div className={cn("min-h-0 overflow-auto", bodyClassName)}>
            {children}
          </div>
          {footer != null && (
            <div className="flex shrink-0 items-center justify-end gap-2">
              {footer}
            </div>
          )}
        </DialogContent>
      </Activity>
    </Dialog>
  );
}
