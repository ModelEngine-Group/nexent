"use client";

import { useEffect, useState } from "react";
import { App, Button, Modal } from "antd";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { canManageModels, getEffectiveRoutePath } from "@/lib/auth";
import log from "@/lib/logger";
import {
  loadMemoryConfig,
  loadMemoryEmbeddingStatus,
  setMemorySwitch,
  subscribeMemorySwitch,
} from "@/services/memoryService";

const MONITORED_PATHS = new Set(["/newchat", "/chat", "/memory"]);

export function MemoryEmbeddingMonitor() {
  const pathname = usePathname();
  const router = useRouter();
  const { locale } = useParams<{ locale: string }>();
  const { isAuthorized, user } = useAuthorizationContext();
  const { isSpeedMode } = useDeployment();
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [revision, setRevision] = useState(0);
  const canConfigure = canManageModels(user?.role, isSpeedMode);

  useEffect(() => {
    const unsubscribe = subscribeMemorySwitch((enabled) => {
      if (!enabled) setOpen(false);
      setRevision((value) => value + 1);
    });
    const recheck = () => setRevision((value) => value + 1);
    window.addEventListener("embeddingModelChanged", recheck);
    return () => {
      unsubscribe();
      window.removeEventListener("embeddingModelChanged", recheck);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setOpen(false);
    if (
      !isAuthorized ||
      !MONITORED_PATHS.has(getEffectiveRoutePath(pathname))
    ) {
      return;
    }
    async function check() {
      try {
        const config = await loadMemoryConfig({ throwOnError: true });
        if (cancelled || !config.memoryEnabled) return;
        const status = await loadMemoryEmbeddingStatus();
        if (!cancelled) setOpen(!status.configured);
      } catch (error) {
        log.error("Failed to check memory embedding configuration", error);
      }
    }
    void check();
    return () => {
      cancelled = true;
    };
  }, [isAuthorized, pathname, revision, user?.id, user?.tenantId]);

  const disableMemory = async () => {
    setSaving(true);
    const saved = await setMemorySwitch(false);
    setSaving(false);
    if (saved) {
      setOpen(false);
    } else {
      message.error(t("useMemory.setMemorySwitchError"));
    }
  };

  return (
    <Modal
      open={open}
      title={t("embedding.memoryUnavailableWarningModal.title")}
      onCancel={() => setOpen(false)}
      closable={!saving}
      maskClosable={false}
      keyboard={!saving}
      footer={[
        <Button key="disable" loading={saving} onClick={disableMemory}>
          {t("embedding.memoryUnavailableWarningModal.disable")}
        </Button>,
        canConfigure && (
          <Button
            key="configure"
            type="primary"
            disabled={saving}
            onClick={() => {
              setOpen(false);
              router.push(`/${locale}/models`);
            }}
          >
            {t("embedding.chatMemoryWarningModal.ok_config")}
          </Button>
        ),
      ]}
    >
      <p>{t("embedding.memoryUnavailableWarningModal.content")}</p>
      {!canConfigure && <p>{t("embedding.chatMemoryWarningModal.tip")}</p>}
    </Modal>
  );
}
