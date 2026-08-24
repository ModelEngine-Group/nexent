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

  /** Fixed body height + inner scroll prevents the form from overflowing the modal. */
  const bodyFrame = "min(90vh, 700px)";

  return (
    <Modal
      open
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
          display: "flex",
          flexDirection: "column",
          height: bodyFrame,
          maxHeight: bodyFrame,
          overflow: "hidden",
        },
      }}
    >
      <div className="flex h-full min-h-0 min-w-0 flex-col">
        <div className="shrink-0 border-b border-slate-100 px-6 py-4">
          <h2 className="text-2xl font-semibold text-slate-900">
            {t("mcpTools.addModal.title")}
          </h2>
        </div>

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
