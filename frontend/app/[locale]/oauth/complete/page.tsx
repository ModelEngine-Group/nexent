"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { Alert, Button, Card, Spin } from "antd";

import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { oauthService } from "@/services/oauthService";

export default function OAuthCompletePage() {
  const params = useParams<{ locale: string }>();
  const locale = params?.locale === "en" ? "en" : "zh";
  const { t } = useTranslation("common");
  const { openRegisterModal } = useAuthenticationContext();
  const [status, setStatus] = useState<"loading" | "ready" | "expired">(
    "loading"
  );

  useEffect(() => {
    let mounted = true;

    oauthService.getPendingOAuth().then((pending) => {
      if (!mounted) return;

      if (!pending) {
        setStatus("expired");
        return;
      }

      openRegisterModal({
        mode: "oauth_complete",
        email: pending.provider_email || "",
        emailReadOnly: !pending.email_required,
      });
      setStatus("ready");
    });

    return () => {
      mounted = false;
    };
  }, [openRegisterModal]);

  if (status === "expired") {
    return (
      <div className="min-h-full w-full flex items-center justify-center px-4 py-8">
        <Card className="w-full max-w-md">
          <Alert
            type="warning"
            showIcon
            message={t("auth.oauthPendingExpired")}
          />
          <Button className="mt-6 w-full" type="primary" href={`/${locale}`}>
            {t("auth.oauthBackHome")}
          </Button>
        </Card>
      </div>
    );
  }

  if (status === "ready") {
    return null;
  }

  return (
    <div className="min-h-full w-full flex flex-col items-center justify-center gap-3 px-4 py-8">
      <Spin />
    </div>
  );
}
