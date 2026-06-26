import { useState, useEffect } from "react";
import { Modal, Input, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";

const { Text } = Typography;

interface McpEditServerModalProps {
  open: boolean;
  onCancel: () => void;
  onSave: (name: string, url: string, authorizationToken?: string | null, customHeaders?: Record<string, string> | null) => Promise<void>;
  initialName: string;
  initialUrl: string;
  initialAuthorizationToken?: string | null;
  initialCustomHeaders?: Record<string, string> | null;
  loading: boolean;
}

export default function McpEditServerModal({
  open,
  onCancel,
  onSave,
  initialName,
  initialUrl,
  initialAuthorizationToken,
  initialCustomHeaders,
  loading,
}: McpEditServerModalProps) {
  const { t } = useTranslation("common");
  const [name, setName] = useState(initialName);
  const [url, setUrl] = useState(initialUrl);
  const [authorizationToken, setAuthorizationToken] = useState(initialAuthorizationToken || "");
  const [customHeaders, setCustomHeaders] = useState(initialCustomHeaders ? JSON.stringify(initialCustomHeaders, null, 2) : "");

  useEffect(() => {
    if (open) {
      setName(initialName);
      setUrl(initialUrl);
      setAuthorizationToken(initialAuthorizationToken || "");
      setCustomHeaders(initialCustomHeaders ? JSON.stringify(initialCustomHeaders, null, 2) : "");
    }
  }, [open, initialName, initialUrl, initialAuthorizationToken, initialCustomHeaders]);

  const handleSave = () => {
    let parsedCustomHeaders: Record<string, string> | null = null;
    if (customHeaders.trim()) {
      try {
        parsedCustomHeaders = JSON.parse(customHeaders.trim());
      } catch {
        parsedCustomHeaders = null;
      }
    }
    onSave(name, url, authorizationToken || null, parsedCustomHeaders);
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
        <div>
          <Text strong>{t("mcpConfig.editServer.authorizationToken")}</Text>
          <Input.Password
            value={authorizationToken}
            onChange={(e) => setAuthorizationToken(e.target.value)}
            placeholder={t("mcpConfig.editServer.authorizationTokenPlaceholder")}
            className="mt-2"
          />
        </div>
        <div>
          <Text strong>{t("mcpConfig.addServer.customHeaders")}</Text>
          <Input.TextArea
            value={customHeaders}
            onChange={(e) => setCustomHeaders(e.target.value)}
            placeholder={t("mcpConfig.addServer.customHeadersPlaceholder")}
            rows={3}
            className="mt-2"
          />
        </div>
      </Space>
    </Modal>
  );
}

