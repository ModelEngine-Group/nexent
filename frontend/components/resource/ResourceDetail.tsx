// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Modal } from "antd";
import type { CSSProperties, ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";
import { Drawer } from "antd";
import { Button } from "antd";
import { X } from "lucide-react";

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
  const presentation = useRepositoryPresentation();
  const { t } = useTranslation("common");
  if (
    presentation?.resourceType === "agent" ||
    presentation?.resourceType === "mcp"
  ) {
    return (
      <Drawer
        open={open}
        onClose={onClose}
        width={608}
        title={null}
        closable={false}
        footer={null}
        classNames={{
          body: "!flex !min-h-0 !flex-col !overflow-hidden !py-0",
          mask:
            presentation.resourceType === "agent" ? "!bg-black/30" : undefined,
        }}
      >
        <div className="relative flex min-h-0 w-full flex-1 flex-col">
          <div className="absolute right-0 top-0 z-20">
            <Button
              type="text"
              icon={<X size={16} />}
              aria-label={t("common.close")}
              onClick={onClose}
            />
          </div>
          {children}
        </div>
      </Drawer>
    );
  }
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
