"use client";

import { useEffect, useRef } from "react";
import { App } from "antd";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { getEffectiveRoutePath } from "@/lib/auth";
import log from "@/lib/logger";
import { loadMemoryEmbeddingStatus } from "@/services/memoryService";

const MONITORED_PATHS = new Set(["/newchat", "/chat", "/memory"]);

export function MemoryEmbeddingMonitor() {
  const pathname = usePathname();
  const { isAuthorized, user } = useAuthorizationContext();
  const { modal } = App.useApp();
  const { t } = useTranslation("common");
  const lastCheckedPathRef = useRef<string | null>(null);

  useEffect(() => {
    const effectivePath = getEffectiveRoutePath(pathname);
    const checkKey = `${user?.tenantId ?? ""}:${effectivePath}`;
    if (
      !isAuthorized ||
      !MONITORED_PATHS.has(effectivePath) ||
      lastCheckedPathRef.current === checkKey
    ) {
      return;
    }

    lastCheckedPathRef.current = checkKey;
    loadMemoryEmbeddingStatus()
      .then((status) => {
        if (!status.configured) {
          modal.warning({
            title: t("embedding.memoryUnavailableWarningModal.title"),
            content: t("embedding.memoryUnavailableWarningModal.content"),
            okText: t("common.confirm"),
          });
        }
      })
      .catch((error) => {
        log.error("Failed to check tenant embedding configuration", error);
        lastCheckedPathRef.current = null;
      });
  }, [isAuthorized, modal, pathname, t, user?.tenantId]);

  return null;
}
