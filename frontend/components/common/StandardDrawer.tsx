import type { ReactNode } from "react";
import { Drawer } from "antd";

import { StandardButton } from "@/components/common/StandardButton";
import { StandardCloseButton } from "@/components/common/StandardCloseButton";

export interface StandardDrawerProps {
  open: boolean;
  title: ReactNode;
  closeLabel: string;
  closeText: ReactNode;
  confirmText?: ReactNode;
  children: ReactNode;
  onClose: () => void;
  onConfirm?: () => void;
  width?: number | string;
  footer?: ReactNode | null;
}

export function StandardDrawer({
  open,
  title,
  closeLabel,
  closeText,
  confirmText,
  children,
  onClose,
  onConfirm,
  width = 560,
  footer,
}: StandardDrawerProps) {
  const defaultFooter = (
    <div className="flex h-8 w-full shrink-0 flex-nowrap items-center justify-end gap-4">
      <StandardButton onClick={onClose}>{closeText}</StandardButton>
      {onConfirm && confirmText !== undefined && (
        <StandardButton variant="primary" onClick={onConfirm}>
          {confirmText}
        </StandardButton>
      )}
    </div>
  );

  return (
    <Drawer
      open={open}
      placement="right"
      size={width}
      onClose={onClose}
      mask={{ closable: false }}
      closable={false}
      title={
        <div className="flex h-[28px] w-full items-center justify-between">
          <span className="max-w-[300px] overflow-hidden whitespace-nowrap text-[20px] ![letter-spacing:0px] leading-[28px] text-[#191919]">
            {title}
          </span>
          <StandardCloseButton ariaLabel={closeLabel} onClick={onClose} />
        </div>
      }
      footer={footer === undefined ? defaultFooter : footer}
      classNames={{
        section:
          "!flex !h-full !flex-col !overflow-hidden !p-6 !shadow-[-2px_0_12px_0_rgba(0,0,0,0.08)]",
        header: "!m-0 !h-[28px] !w-full !shrink-0 !border-0 !p-0",
        title: "!w-full !min-w-0",
        body: "!flex !min-h-0 !w-full !flex-1 !overflow-y-auto !px-0 !py-4",
        footer: "!h-8 !w-full !shrink-0 !border-0 !p-0",
      }}
    >
      {children}
    </Drawer>
  );
}
