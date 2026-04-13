"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Card, List, Modal, Space, Divider, message } from "antd";
import { Github, Unlink, Link2, Plus } from "lucide-react";

import {
  oauthService,
  type OAuthAccount,
  type OAuthProvider,
} from "@/services/oauthService";

const providerIcons: Record<string, React.ReactNode> = {
  github: <Github size={20} />,
};

export function OAuthAccountsSection() {
  const { t } = useTranslation("common");
  const [accounts, setAccounts] = useState<OAuthAccount[]>([]);
  const [enabledProviders, setEnabledProviders] = useState<OAuthProvider[]>([]);
  const [loading, setLoading] = useState(false);
  const [unlinkTarget, setUnlinkTarget] = useState<OAuthAccount | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    const [linked, providers] = await Promise.all([
      oauthService.getLinkedAccounts(),
      oauthService.getEnabledProviders(),
    ]);
    setAccounts(linked);
    setEnabledProviders(providers);
    setLoading(false);
  };

  const handleUnlink = async () => {
    if (!unlinkTarget) return;

    try {
      const success = await oauthService.unlinkAccount(unlinkTarget.provider);
      if (success) {
        message.success(t("auth.unlinkSuccess"));
        await loadData();
      } else {
        message.error(t("auth.unlinkFailed"));
      }
    } finally {
      setUnlinkTarget(null);
    }
  };

  const linkedProviders = new Set(accounts.map((a) => a.provider));
  const unlinkedProviders = enabledProviders.filter(
    (p) => !linkedProviders.has(p.name)
  );

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
      {accounts.length === 0 && unlinkedProviders.length === 0 ? (
        <div className="text-center py-6 text-gray-400">
          {t("auth.noLinkedAccounts")}
        </div>
      ) : (
        <>
          {accounts.length > 0 && (
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

          {unlinkedProviders.length > 0 && (
            <>
              <Divider style={{ margin: "12px 0" }} />
              <div className="flex flex-wrap gap-2">
                {unlinkedProviders.map((provider) => (
                  <Button
                    key={provider.name}
                    icon={<Plus size={14} />}
                    onClick={() =>
                      oauthService.startOAuthLogin(provider.name)
                    }
                  >
                    {t("auth.linkAccount")} {provider.display_name}
                  </Button>
                ))}
              </div>
            </>
          )}
        </>
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
