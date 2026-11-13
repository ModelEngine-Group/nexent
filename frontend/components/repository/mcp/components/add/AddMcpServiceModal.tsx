// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useCallback, useRef, useState } from "react";
import { Drawer } from "antd";
import { useTranslation } from "react-i18next";
import { Button } from "antd";
import { X } from "lucide-react";
import AddMcpServiceLocalSection from "./local/AddMcpServiceLocalSection";
import { useMcpServerList } from "@/hooks/mcp/useMcpServerList";

interface AddMcpServiceModalProps {
  open: boolean;
  onClose: () => void;
}

export default function AddMcpServiceModal({
  open,
  onClose,
}: AddMcpServiceModalProps) {
  const { t } = useTranslation("common");
  const { enableUploadImage } = useMcpServerList({ enabled: open });
  const submittingRef = useRef(false);
  const [submitting, setSubmittingState] = useState(false);

  const handleClose = useCallback(() => {
    if (submittingRef.current) return;
    onClose();
  }, [onClose]);

  const setSubmitting = useCallback((v: boolean) => {
    submittingRef.current = v;
    setSubmittingState(v);
  }, []);

  if (!open) return null;

  return (
    <Drawer
      open
      placement="right"
      size="min(768px, 100vw)"
      title={
        <div className="flex h-7 items-center justify-between">
          <span className="text-xl font-normal leading-7 text-[#191919]">
            {t("mcpTools.addModal.title")}
          </span>
          {!submitting && (
            <Button
              type="text"
              icon={<X size={16} />}
              aria-label={t("common.close")}
              onClick={handleClose}
            />
          )}
        </div>
      }
      closable={false}
      onClose={handleClose}
      mask={{ closable: !submitting }}
      classNames={{
        section: "!p-6 !shadow-[-2px_0_12px_0_rgba(0,0,0,0.08)]",
        header: "!shrink-0 !border-0 !p-0",
        body: "!flex !min-h-0 !flex-col !overflow-hidden !p-0",
      }}
    >
      <AddMcpServiceLocalSection
        active
        enableUploadImage={enableUploadImage}
        onAdded={onClose}
        onClose={handleClose}
        onSubmittingChange={setSubmitting}
      />
    </Drawer>
  );
}
