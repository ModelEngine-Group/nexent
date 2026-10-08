"use client";

import { Modal } from "antd";
import type { CSSProperties, ReactNode } from "react";

export interface ResourceDetailProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  width?: number;
  className?: string;
  bodyStyle?: CSSProperties;
}

/** Shared centered detail dialog for resource cards. */
export default function ResourceDetail({
  open,
  onClose,
  children,
  width = 720,
  className,
  bodyStyle,
}: ResourceDetailProps) {
  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={width}
      centered
      destroyOnHidden
      title={null}
      className={className}
      styles={{ body: bodyStyle }}
    >
      {children}
    </Modal>
  );
}
