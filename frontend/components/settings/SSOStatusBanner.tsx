"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, message } from "antd";
import { CheckCircle, AlertTriangle, RefreshCw } from "lucide-react";
import { oauthService } from "@/services/oauthService";
import log from "@/lib/logger";

interface SSOStatusBannerProps {
  compact?: boolean;
}

export function SSOStatusBanner({ compact = false }: SSOStatusBannerProps) {
  const { t } = useTranslation("common");
  const [status, setStatus] = useState<oauthService.SSOCheckResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [reauthorizing, setReauthorizing] = useState(false);

  useEffect(() => {
    checkSSOStatus();
  }, []);

  const checkSSOStatus = async () => {
    setLoading(true);
    try {
      const result = await oauthService.getSSOStatus();
      setStatus(result);
    } catch (error) {
      log.error("Failed to check SSO status:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleReauthorize = async () => {
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

  if (!status?.sso_enabled || !status?.linked) {
    return null;
  }

  if (compact) {
    return (
      <div className="flex items-center gap-2">
        {status.has_token ? (
          <span className="flex items-center gap-1 text-green-600 text-sm">
            <CheckCircle size={14} />
            {t("auth.ssoConnected")}
          </span>
        ) : (
          <Button
            type="link"
            size="small"
            danger
            icon={<AlertTriangle size={14} />}
            onClick={handleReauthorize}
            loading={reauthorizing}
          >
            {t("auth.ssoDisconnected")}
          </Button>
        )}
      </div>
    );
  }

  if (status.has_token) {
    return (
      <Alert
        type="success"
        showIcon
        icon={<CheckCircle size={16} />}
        message={t("auth.ssoStatusTitle")}
        description={t("auth.ssoConnectedDesc", { provider: status.provider?.toUpperCase() })}
        className="mb-4"
      />
    );
  }

  return (
    <Alert
      type="warning"
      showIcon
      icon={<AlertTriangle size={16} />}
      message={t("auth.ssoDisconnectedTitle")}
      description={
        <div className="flex items-center justify-between">
          <span>{t("auth.ssoDisconnectedDesc", { provider: status.provider?.toUpperCase() })}</span>
          <Button
            type="primary"
            size="small"
            icon={<RefreshCw size={14} />}
            onClick={handleReauthorize}
            loading={reauthorizing}
          >
            {t("auth.reauthorize")}
          </Button>
        </div>
      }
      className="mb-4"
    />
  );
}
