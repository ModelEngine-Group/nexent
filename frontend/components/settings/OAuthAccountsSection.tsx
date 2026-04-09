"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Card, List, Modal, Space, message } from "antd";
import { Github, Unlink, Link2 } from "lucide-react";

import { oauthService, type OAuthAccount } from "@/services/oauthService";

export function OAuthAccountsSection() {
  const { t } = useTranslation("common");
  const [accounts, setAccounts] = useState<OAuthAccount[]>([]);
  const [loading, setLoading] = useState(false);
  const [unlinkTarget, setUnlinkTarget] = useState<OAuthAccount | null>(null);

  useEffect(() => {
    loadAccounts();
  }, []);

  const loadAccounts = async () => {
    setLoading(true);
    const result = await oauthService.getLinkedAccounts();
    setAccounts(result);
    setLoading(false);
  };

  const handleUnlink = async () => {
    if (!unlinkTarget) return;

    try {
      const success = await oauthService.unlinkAccount(unlinkTarget.provider);
      if (success) {
        message.success(t("auth.unlinkSuccess"));
        await loadAccounts();
      } else {
        message.error(t("auth.unlinkFailed"));
      }
    } finally {
      setUnlinkTarget(null);
    }
  };

  const providerIcons: Record<string, React.ReactNode> = {
    github: <Github size={20} />,
    wechat: <Link2 size={20} />,
  };

  return (
    <Card
      title={
        <Space>
          <span>{t("auth.linkedAccounts")}</span>
        </Space>
      }
      loading={loading}
      className="mt-4"
    >
      {accounts.length === 0 ? (
        <div className="text-center py-6 text-gray-400">
          {t("auth.noLinkedAccounts")}
        </div>
      ) : (
        <List
          dataSource={accounts}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button
                  key="unlink"
                  type="link"
                  danger
                  size="small"
                  icon={<Unlink size={14} />}
                  onClick={() => setUnlinkTarget(item)}
                >
                  {t("auth.unlinkAccount")}
                </Button>,
              ]}
            >
              <List.Item.Meta
                avatar={
                  <div className="w-10 h-10 rounded-full bg-gray-100 flex items-center justify-center">
                    {providerIcons[item.provider] || <Link2 size={20} />}
                  </div>
                }
                title={item.provider_username || item.provider}
                description={item.provider_email || "-"}
              />
            </List.Item>
          )}
        />
      )}

      <Modal
        title={t("auth.unlinkConfirm", { provider: unlinkTarget?.provider || "" })}
        open={!!unlinkTarget}
        onOk={handleUnlink}
        onCancel={() => setUnlinkTarget(null)}
        okText={t("auth.confirm")}
        cancelText={t("auth.cancel")}
        okButtonProps={{ danger: true }}
      >
        <p>{t("auth.unlinkConfirm", { provider: unlinkTarget?.provider || "" })}</p>
      </Modal>
    </Card>
  );
}
