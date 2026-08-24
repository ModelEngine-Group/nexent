import { useCallback, useRef, useState } from "react";
import { Modal } from "antd";
import { useTranslation } from "react-i18next";
import { MCP_ADD_SERVICE_MODAL_WIDTH_MARKETS } from "@/const/mcpTools";
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

  const handleClose = useCallback(() => {
    if (submittingRef.current) return;
    onClose();
  }, [onClose]);

  const setSubmitting = useCallback((v: boolean) => {
    submittingRef.current = v;
  }, []);

  if (!open) return null;

  return (
    <Modal
      open
      title={
        <div>
          <div className="text-xl font-semibold leading-7 text-slate-900">
            {t("mcpTools.addModal.title")}
          </div>
          <div className="mt-1 text-sm font-normal text-slate-500">
            {t("mcpTools.addModal.subtitle")}
          </div>
        </div>
      }
      footer={null}
      closable={!submittingRef.current}
      centered
      width={MCP_ADD_SERVICE_MODAL_WIDTH_MARKETS}
      onCancel={handleClose}
      maskClosable={!submittingRef.current}
      wrapClassName="[&_.ant-modal]:transition-[width] [&_.ant-modal]:duration-300 [&_.ant-modal]:ease-in-out"
      styles={{
        mask: { background: "rgba(4, 4, 4, 0.6)", backdropFilter: "blur(2px)" },
        body: {
          padding: 0,
          maxHeight: "90vh",
          overflow: "hidden",
        },
      }}
    >
      <div className="flex max-h-[90vh] min-h-0 min-w-0 flex-col">
        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]">
          <AddMcpServiceLocalSection
            active
            enableUploadImage={enableUploadImage}
            onAdded={onClose}
            onSubmittingChange={setSubmitting}
          />
        </div>
      </div>
    </Modal>
  );
}
