"use client";

import { useTranslation } from "react-i18next";
import { Button, Modal, Space, Typography } from "antd";

const { Paragraph, Text } = Typography;

export interface DebugPromptCompareModalProps {
  open: boolean;
  originalFullPrompt: string;
  optimizedFullPrompt: string;
  onClose: () => void;
  onApply: () => void;
  applying?: boolean;
}

export default function DebugPromptCompareModal({
  open,
  originalFullPrompt,
  optimizedFullPrompt,
  onClose,
  onApply,
  applying,
}: DebugPromptCompareModalProps) {
  const { t } = useTranslation("common");

  return (
    <Modal
      title={t("agent.debug.promptCompare.title", "Prompt compare")}
      open={open}
      onCancel={onClose}
      width={1200}
      footer={
        <Space>
          <Button onClick={onClose}>
            {t("agent.debug.promptCompare.close", "Close")}
          </Button>
          <Button
            type="primary"
            onClick={onApply}
            disabled={!optimizedFullPrompt.trim()}
            loading={applying}
          >
            {t("agent.debug.promptCompare.apply", "Apply")}
          </Button>
        </Space>
      }
      destroyOnHidden
    >
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="border border-gray-200 rounded-md p-3 bg-gray-50">
          <Text type="secondary" className="text-xs">
            {t("agent.debug.promptCompare.original", "Original")}
          </Text>
          <Paragraph
            style={{ whiteSpace: "pre-wrap", minHeight: 520, marginBottom: 0 }}
            className="font-mono text-sm"
          >
            {originalFullPrompt || "-"}
          </Paragraph>
        </div>
        <div className="border border-gray-200 rounded-md p-3">
          <Text type="secondary" className="text-xs">
            {t("agent.debug.promptCompare.optimized", "Optimized")}
          </Text>
          <Paragraph
            style={{ whiteSpace: "pre-wrap", minHeight: 520, marginBottom: 0 }}
            className="font-mono text-sm"
          >
            {optimizedFullPrompt || "-"}
          </Paragraph>
        </div>
      </div>
    </Modal>
  );
}
