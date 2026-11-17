// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Modal } from "antd";
import { RESOURCE_REPOSITORY_DETAIL_DRAWER_WIDTH } from "@/const/resourceRepository";
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

/** Render repository details in a side panel and legacy details in a modal. */
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
    presentation?.resourceType === "mcp" ||
    presentation?.resourceType === "skill"
  ) {
    return (
      <Drawer
        open={open}
        onClose={onClose}
        width={`min(${RESOURCE_REPOSITORY_DETAIL_DRAWER_WIDTH}px, 100vw)`}
        title={null}
        closable={false}
        footer={null}
        styles={{
          section: { borderRadius: 0 },
          wrapper: { borderRadius: 0 },
        }}
        classNames={{
          root: "resource-detail-drawer !rounded-none [&_.ant-drawer-content-wrapper]:!rounded-none [&_.ant-drawer-section]:!rounded-none [&_.ant-drawer-content]:!rounded-none",
          wrapper: "!rounded-none",
          section: "!rounded-none",
          body: "!flex !min-h-0 !flex-col !overflow-hidden !pt-6 !pb-0",
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
