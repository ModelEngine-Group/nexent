import type { ReactNode } from "react";
import { Modal } from "antd";

import { StandardButton } from "@/components/common/StandardButton";
import { StandardCloseButton } from "@/components/common/StandardCloseButton";
import { cn } from "@/lib/utils";

export type StandardModalAction = () => boolean | void;

export interface StandardModalProps {
  open: boolean;
  title: ReactNode;
  closeLabel: string;
  cancelText: ReactNode;
  confirmText: ReactNode;
  children: ReactNode;
  onOpenChange: (open: boolean) => void;
  onClose?: StandardModalAction;
  onCancel?: StandardModalAction;
  onConfirm?: StandardModalAction;
  width?: number | string;
  height?: number | string;
  maxHeight?: number | string;
  bodyClassName?: string;
  footer?: ReactNode | null;
}

export function StandardModal({
  open,
  title,
  closeLabel,
  cancelText,
  confirmText,
  children,
  onOpenChange,
  onClose,
  onCancel,
  onConfirm,
  width = 480,
  height,
  maxHeight,
  bodyClassName,
  footer,
}: StandardModalProps) {
  const hasHeightConstraint = height !== undefined || maxHeight !== undefined;

  const requestClose = (action?: StandardModalAction) => {
    if (action?.() === false) return;
    onOpenChange(false);
  };

  const defaultFooter = (
    <div className="flex h-8 w-full flex-nowrap items-center justify-end gap-4">
      <StandardButton onClick={() => requestClose(onCancel)}>
        {cancelText}
      </StandardButton>
      <StandardButton variant="primary" onClick={() => requestClose(onConfirm)}>
        {confirmText}
      </StandardButton>
    </div>
  );

  return (
    <Modal
      open={open}
      width={width}
      styles={
        hasHeightConstraint
          ? {
              container: {
                ...(height === undefined ? {} : { height }),
                ...(maxHeight === undefined ? {} : { maxHeight }),
              },
            }
          : undefined
      }
      centered
      closable={false}
      mask={{ closable: false }}
      keyboard={false}
      footer={footer === undefined ? defaultFooter : footer}
      onCancel={() => requestClose(onClose)}
      title={
        <div className="flex h-6 w-full items-center justify-between">
          <span className="text-[16px] ![letter-spacing:0px] font-bold leading-6 text-[#1a1a1a]">
            {title}
          </span>
          <StandardCloseButton
            ariaLabel={closeLabel}
            onClick={() => requestClose(onClose)}
          />
        </div>
      }
      classNames={{
        container: cn(
          "!rounded-[8px] !border !border-solid !border-[#c9c9c9] !p-6 !shadow-[0_0_15px_0_rgba(26,26,26,0.1)]",
          hasHeightConstraint && "!flex !flex-col !overflow-hidden"
        ),
        header: "!m-0 !h-6 !w-full !shrink-0 !border-0 !p-0",
        body: cn(
          "!m-0 !max-h-[50vh] !overflow-y-auto !px-0 !py-4",
          hasHeightConstraint &&
            "!max-h-none !min-h-0 !flex !flex-1 !flex-col",
          bodyClassName
        ),
        footer: "!m-0 !h-8 !w-full !shrink-0 !border-0 !p-0",
      }}
    >
      {children}
    </Modal>
  );
}
