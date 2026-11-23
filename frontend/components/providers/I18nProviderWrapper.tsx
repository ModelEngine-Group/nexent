// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { ReactNode, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { I18nextProvider } from "react-i18next";

import i18n, { loadLocaleMessages } from "@/app/i18n";
import { getBrowserTabLogo, getBrowserTabTitle } from "@/lib/projectBranding";
import {
  useGlobalConfigStore,
  useGlobalConfigStoreAllLanguage,
} from "@/stores/global";

interface I18nProviderWrapperProps {
  children: ReactNode;
  locale?: string;
}

const TRANSPARENT_TAB_ICON =
  "data:image/svg+xml," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>'
  );

export default function I18nProviderWrapper({
  children,
  locale: initialLocale,
}: I18nProviderWrapperProps) {
  const [loaded, setLoaded] = useState(false);
  const [tabIcon, setTabIcon] = useState(TRANSPARENT_TAB_ICON);
  const pathname = usePathname();
  const { config, setConfig } = useGlobalConfigStore();
  const { setAllConfig } = useGlobalConfigStoreAllLanguage();
  const targetLocale =
    initialLocale || pathname.split("/").filter(Boolean)[0] || "zh";

  useEffect(() => {
    const icon = getBrowserTabLogo();
    const image = new Image();
    image.onload = () => setTabIcon(icon);
    image.src = icon;
    return () => {
      image.onload = null;
    };
  }, []);

  useEffect(() => {
    let isCurrentEffect = true;

    const initI18n = async () => {
      const { resourcesCustom } = await loadLocaleMessages(targetLocale);
      if (!isCurrentEffect) return;

      const localeKey = targetLocale.toLowerCase().startsWith("zh")
        ? "zh"
        : "en";
      setConfig(resourcesCustom[localeKey].custom);
      setAllConfig(resourcesCustom);
      await i18n.changeLanguage(localeKey);
      if (!isCurrentEffect) return;

      document.cookie = `NEXT_LOCALE=${targetLocale}; path=/; max-age=31536000`;
      setLoaded(true);
    };

    void initI18n();

    return () => {
      isCurrentEffect = false;
    };
  }, [targetLocale, setAllConfig, setConfig]);

  return (
    <>
      <title>{getBrowserTabTitle(config)}</title>
      <link rel="icon" href={tabIcon} />
      <link rel="shortcut icon" href={tabIcon} />
      <link rel="apple-touch-icon" href={tabIcon} />
      {loaded && <I18nextProvider i18n={i18n}>{children}</I18nextProvider>}
    </>
  );
}
