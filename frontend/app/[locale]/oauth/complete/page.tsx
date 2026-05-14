"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Alert, Button, Card, Spin, Typography } from "antd";

import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { oauthService } from "@/services/oauthService";

const { Text } = Typography;

export default function OAuthCompletePage() {
  const params = useParams<{ locale: string }>();
  const locale = params?.locale === "en" ? "en" : "zh";
  const { openRegisterModal } = useAuthenticationContext();
  const [loading, setLoading] = useState(true);
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    let mounted = true;

    oauthService.getPendingOAuth().then((pending) => {
      if (!mounted) return;

      if (!pending) {
        setExpired(true);
        setLoading(false);
        return;
      }

      openRegisterModal({
        mode: "oauth_complete",
        email: pending.provider_email || "",
        emailReadOnly: !pending.email_required,
        provider: pending.provider,
        providerUsername: pending.provider_username,
      });
      setLoading(false);
    });

    return () => {
      mounted = false;
    };
  }, [openRegisterModal]);

  if (expired) {
    return (
      <div className="min-h-full w-full flex items-center justify-center px-4 py-8">
        <Card className="w-full max-w-md">
          <Alert
            type="warning"
            showIcon
            message={
              locale === "en"
                ? "OAuth setup session is invalid or expired."
                : "OAuth 补充信息会话已失效，请重新登录。"
            }
          />
          <Button className="mt-6 w-full" type="primary" href={`/${locale}`}>
            {locale === "en" ? "Back to home" : "返回首页"}
          </Button>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-full w-full flex flex-col items-center justify-center gap-3 px-4 py-8">
      {loading && <Spin />}
      <Text type="secondary">
        {locale === "en"
          ? "Preparing account setup..."
          : "正在准备账号补充信息..."}
      </Text>
    </div>
  );
}
