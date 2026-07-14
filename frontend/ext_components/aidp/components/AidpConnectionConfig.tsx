import React, { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";

import { Button, Input, Card, Space, message } from "antd";
import {
  SaveOutlined,
  ApiOutlined,
  DeleteOutlined,
} from "@ant-design/icons";

import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";

interface AidpConnectionConfigProps {
  serverUrl: string;
  apiKey: string;
  isConnected: boolean;
  onConnectionChange: (serverUrl: string, apiKey: string) => void;
  onConnectionClear: () => void;
}

const AidpConnectionConfig: React.FC<AidpConnectionConfigProps> = ({
  serverUrl,
  apiKey,
  isConnected,
  onConnectionChange,
  onConnectionClear,
}) => {
  const { t } = useTranslation();

  const [urlDraft, setUrlDraft] = useState(serverUrl);
  const [keyDraft, setKeyDraft] = useState(apiKey);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  // Sync drafts when props change externally (e.g. initial load)
  useEffect(() => {
    setUrlDraft(serverUrl);
    setKeyDraft(apiKey);
  }, [serverUrl, apiKey]);

  const handleSave = useCallback(async () => {
    const trimmedUrl = urlDraft.trim();
    const trimmedKey = keyDraft.trim();

    if (!trimmedUrl || !trimmedKey) {
      message.warning(t("aidpKnowledge.fillCredentialsFirst"));
      return;
    }

    setSaving(true);
    try {
      localStorage.setItem("aidp_kb_server_url", trimmedUrl);
      localStorage.setItem("aidp_kb_api_key", trimmedKey);
      onConnectionChange(trimmedUrl, trimmedKey);
      message.success(t("aidpKnowledge.savedSuccess"));
    } catch (error) {
      message.error(t("aidpKnowledge.saveFailed"));
    } finally {
      setSaving(false);
    }
  }, [urlDraft, keyDraft, onConnectionChange, t]);

  const handleTestConnection = useCallback(async () => {
    const trimmedUrl = (urlDraft || serverUrl).trim();
    const trimmedKey = (keyDraft || apiKey).trim();

    if (!trimmedUrl || !trimmedKey) {
      message.warning(t("aidpKnowledge.fillCredentialsFirst"));
      return;
    }

    setTesting(true);
    try {
      const result = await aidpKnowledgeService.countKbs(trimmedUrl, trimmedKey);
      message.success(
        t("aidpKnowledge.testConnectionSuccess", { count: result.count })
      );

      // Persist if not yet saved
      if (trimmedUrl !== serverUrl || trimmedKey !== apiKey) {
        localStorage.setItem("aidp_kb_server_url", trimmedUrl);
        localStorage.setItem("aidp_kb_api_key", trimmedKey);
        onConnectionChange(trimmedUrl, trimmedKey);
      }
    } catch (error) {
      message.error(t("aidpKnowledge.testConnectionFailed"));
    } finally {
      setTesting(false);
    }
  }, [urlDraft, keyDraft, serverUrl, apiKey, onConnectionChange, t]);

  const handleClear = useCallback(() => {
    localStorage.removeItem("aidp_kb_server_url");
    localStorage.removeItem("aidp_kb_api_key");
    setUrlDraft("");
    setKeyDraft("");
    onConnectionClear();
    message.success(t("aidpKnowledge.clearedSuccess"));
  }, [onConnectionClear, t]);

  return (
    <Card size="small" className="mb-4">
      <div className="flex items-start gap-4 flex-wrap">
        <div className="flex-1 min-w-[200px]">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            {t("aidpKnowledge.serverUrl")}
          </label>
          <Input
            value={urlDraft}
            onChange={(e) => setUrlDraft(e.target.value)}
            placeholder={t("aidpKnowledge.serverUrlPlaceholder")}
          />
        </div>
        <div className="flex-1 min-w-[200px]">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            {t("aidpKnowledge.apiKey")}
          </label>
          <Input.Password
            value={keyDraft}
            onChange={(e) => setKeyDraft(e.target.value)}
            placeholder={t("aidpKnowledge.apiKeyPlaceholder")}
          />
        </div>
        <div className="flex items-end gap-2 pt-5">
          <Space>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saving}
              onClick={handleSave}
            >
              {t("aidpKnowledge.save")}
            </Button>
            <Button
              icon={<ApiOutlined />}
              loading={testing}
              onClick={handleTestConnection}
            >
              {t("aidpKnowledge.testConnection")}
            </Button>
            <Button
              danger
              icon={<DeleteOutlined />}
              onClick={handleClear}
            >
              {t("aidpKnowledge.clear")}
            </Button>
          </Space>
        </div>
      </div>
      {isConnected && (
        <div className="mt-2 text-xs text-green-600">
          {t("aidpKnowledge.connected")}
        </div>
      )}
    </Card>
  );
};

export default AidpConnectionConfig;
