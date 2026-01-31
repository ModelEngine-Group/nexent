import { Modal, Button, Spin } from "antd";
import { useTranslation } from "react-i18next";

interface McpContainerLogsModalProps {
  open: boolean;
  onCancel: () => void;
  loading: boolean;
  logs: string;
  containerId: string;
}

export default function McpContainerLogsModal({
  open,
  onCancel,
  loading,
  logs,
  containerId,
}: McpContainerLogsModalProps) {
  const { t } = useTranslation("common");

  return (
    <Modal
      title={`${t("mcpConfig.containerLogs.title")} - ${containerId?.substring(0, 12)}`}
      open={open}
      onCancel={onCancel}
      width={800}
      footer={[<Button key="close" onClick={onCancel}>{t("mcpConfig.modal.close")}</Button>]}
    >
      <Spin spinning={loading} tip={t("mcpConfig.containerLogs.loading")}>
        <pre className="bg-gray-100 p-4 rounded max-h-[500px] overflow-auto whitespace-pre-wrap text-xs font-mono">
          {logs || t("mcpConfig.containerLogs.empty")}
        </pre>
      </Spin>
    </Modal>
  );
}

