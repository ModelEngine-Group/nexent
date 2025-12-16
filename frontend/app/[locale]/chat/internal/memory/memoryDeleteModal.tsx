import React from "react";
import { useTranslation, Trans } from "react-i18next";
import { Modal } from "antd";
import { WarningFilled } from "@ant-design/icons";
import { MemoryDeleteModalProps } from "@/types/memory";

/**
 * Hosts the "Clear Memory" secondary confirmation popup window and is responsible only for UI display.
 * The upper-level component is responsible for controlling visible and callback logic.
 */
const MemoryDeleteModal: React.FC<MemoryDeleteModalProps> = ({
  visible,
  targetTitle,
  onOk,
  onCancel,
}) => {
  const { t } = useTranslation();
  return (
    <Modal
      open={visible}
      title={
        <div className="flex items-center gap-2 text-lg font-bold">
          <span>{t("memoryDeleteModal.title")}</span>
        </div>
      }
      onOk={onOk}
      onCancel={onCancel}
      okText={t("memoryDeleteModal.clear")}
      cancelText={t("common.cancel")}
      okButtonProps={{ danger: true }}
      destroyOnClose
    >
      <div className="flex items-start gap-3 mt-4">
        <WarningFilled
          className="text-yellow-500 mt-1 mr-2"
          style={{ fontSize: "48px" }}
        />
        <div className="space-y-2">
          <p>
            <Trans
              i18nKey="memoryDeleteModal.description"
              values={{ title: targetTitle || "" }}
              components={{ strong: <strong /> }}
            />
          </p>
          <p className="text-gray-500 text-sm">
            {t("memoryDeleteModal.prompt")}
          </p>
        </div>
      </div>
    </Modal>
  );
};

export default MemoryDeleteModal;
