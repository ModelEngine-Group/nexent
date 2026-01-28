import { useState, useEffect } from "react";
import { Modal, Input, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";

const { Text } = Typography;

interface McpEditServerModalProps {
  open: boolean;
  onCancel: () => void;
  onSave: (name: string, url: string) => Promise<void>;
  initialName: string;
  initialUrl: string;
  loading: boolean;
}

export default function McpEditServerModal({
  open,
  onCancel,
  onSave,
  initialName,
  initialUrl,
  loading,
}: McpEditServerModalProps) {
  const { t } = useTranslation("common");
  const [name, setName] = useState(initialName);
  const [url, setUrl] = useState(initialUrl);

  useEffect(() => {
    if (open) {
      setName(initialName);
      setUrl(initialUrl);
    }
  }, [open, initialName, initialUrl]);

  const handleSave = () => {
    onSave(name, url);
  };

  return (
    <Modal
      title={t("mcpConfig.editServer.title")}
      open={open}
      onCancel={onCancel}
      onOk={handleSave}
      okButtonProps={{ loading: loading }}
      okText={t("common.save")}
      cancelText={t("common.cancel")}
    >
      <Space direction="vertical" className="w-full">
        <div>
          <Text strong>{t("mcpConfig.editServer.serviceName")}</Text>
          <Input value={name} onChange={(e) => setName(e.target.value)} className="mt-2" />
        </div>
        <div>
          <Text strong>{t("mcpConfig.editServer.mcpUrl")}</Text>
          <Input value={url} onChange={(e) => setUrl(e.target.value)} className="mt-2" />
        </div>
      </Space>
    </Modal>
  );
}

