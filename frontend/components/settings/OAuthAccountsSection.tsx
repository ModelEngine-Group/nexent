"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Card, Modal, message } from "antd";
import { Github, Unlink, Link2, Plus, RefreshCw, ExternalLink } from "lucide-react";

import {
  oauthService,
  type OAuthAccount,
  type OAuthProvider,
} from "@/services/oauthService";
import log from "@/lib/logger";

const providerIcons: Record<string, React.ReactNode> = {
  github: <Github size={20} />,
  gde: <ExternalLink size={20} />,
};

interface ProviderRow {
  name: string;
  display_name: string;
  linked: boolean;
  account?: OAuthAccount;
}

export function OAuthAccountsSection() {
  const { t } = useTranslation("common");
  const [accounts, setAccounts] = useState<OAuthAccount[]>([]);
  const [enabledProviders, setEnabledProviders] = useState<OAuthProvider[]>([]);
  const [ssoConfig, setSsoConfig] = useState<{ sso_enabled: boolean; sso_provider: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [unlinkTarget, setUnlinkTarget] = useState<OAuthAccount | null>(null);
  const [reauthorizing, setReauthorizing] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [linked, providers, sso] = await Promise.all([
        oauthService.getLinkedAccounts(),
        oauthService.getEnabledProviders(),
        oauthService.getSSOConfig(),
      ]);
      setAccounts(linked);
      setEnabledProviders(providers);
      setSsoConfig(sso);
    } catch (error) {
      log.error("Failed to load OAuth data:", error);
    } finally {
      setLoading(false);
    }
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

  const handleReauthorize = async (provider: string) => {
    setReauthorizing(true);
    try {
      const result = await oauthService.reauthorizeSSO();
      if (result?.reauthorize_url) {
        window.location.href = result.reauthorize_url;
      } else {
        message.error(t("auth.reauthorizeFailed"));
      }
    } catch (error) {
      log.error("Failed to reauthorize SSO:", error);
      message.error(t("auth.reauthorizeFailed"));
    } finally {
      setReauthorizing(false);
    }
  };

  const accountMap = new Map(accounts.map((a) => [a.provider, a]));
  const rows: ProviderRow[] = enabledProviders.map((p) => {
    const account = accountMap.get(p.name);
    return {
      name: p.name,
      display_name: p.display_name,
      linked: !!account,
      account: account,
    };
  });

  return (
    <Card
      title={<span>{t("auth.linkedAccounts")}</span>}
      loading={loading}
      className="mt-4"
    >
      {rows.length === 0 ? (
        <div className="text-center py-6 text-gray-400">
          {t("auth.noLinkedAccounts")}
        </div>
      ) : (
        <div className="flex flex-col">
          {rows.map((row) => (
            <div
              key={row.name}
              className="flex items-center justify-between py-3 border-b last:border-b-0"
            >
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-gray-100 flex items-center justify-center shrink-0">
                  {providerIcons[row.name] || <Link2 size={20} />}
                </div>
                <div className="min-w-0">
                  <div className="font-medium truncate">
                    {row.display_name}
                  </div>
                  <div className="text-sm text-gray-500 truncate">
                    {row.linked
                      ? row.account!.provider_username || row.account!.provider_email || "-"
                      : t("auth.noLinkedAccounts")}
                  </div>
                </div>
              </div>
              {row.linked ? (
                <div className="flex items-center gap-2">
                  {row.name === ssoConfig?.sso_provider && (
                    <Button
                      type="link"
                      size="small"
                      icon={<RefreshCw size={14} />}
                      onClick={() => handleReauthorize(row.name)}
                      loading={reauthorizing}
                    >
                      {t("auth.reauthorize")}
                    </Button>
                  )}
                  <Button
                    type="link"
                    danger
                    size="small"
                    icon={<Unlink size={14} />}
                    onClick={() => setUnlinkTarget(row.account!)}
                  >
                    {t("auth.unlinkAccount")}
                  </Button>
                </div>
              ) : (
                <Button
                  size="small"
                  icon={<Plus size={14} />}
                  onClick={() => oauthService.startOAuthLink(row.name)}
                >
                  {t("auth.linkAccount")}
                </Button>
              )}
            </div>
          ))}
        </div>
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
