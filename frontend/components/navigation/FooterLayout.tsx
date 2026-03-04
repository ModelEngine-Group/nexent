"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import Link from "next/link";
import { APP_VERSION } from "@/const/constants";
import { versionService } from "@/services/versionService";
import log from "@/lib/logger";

/**
 * Footer component with copyright, version, and links
 * Displays at the bottom of the page
 */
export function FooterLayout() {
  const { t } = useTranslation("common");
  const [appVersion, setAppVersion] = useState<string>("");

  // Get app version on mount
  useEffect(() => {
    const fetchAppVersion = async () => {
      try {
        const version = await versionService.getAppVersion();
        setAppVersion(version);
      } catch (error) {
        log.error("Failed to fetch app version:", error);
        setAppVersion(APP_VERSION); // Fallback
      }
    };

    fetchAppVersion();
  }, []);

  return (
    <div className="py-[9px] px-4 w-full flex items-center justify-between border-t border-b">
      <div className="flex items-center gap-8">
        <span className="text-sm text-slate-900 dark:text-white">
          {t("page.copyright", { year: new Date().getFullYear() })}
        </span>
      </div>
    </div>
  );
}
