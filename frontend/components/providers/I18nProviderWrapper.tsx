"use client";

import { ReactNode, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { I18nextProvider } from "react-i18next";

import i18n, { loadLocaleMessages } from "@/app/i18n";
import { useGlobalConfigStore, useGlobalConfigStoreAllLanguage } from "@/stores/global";

interface I18nProviderWrapperProps {
  children: ReactNode;
  locale?: string;
}

export default function I18nProviderWrapper({
  children,
  locale: initialLocale,
}: I18nProviderWrapperProps) {
  const [mounted, setMounted] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const pathname = usePathname();
  const { setConfig } = useGlobalConfigStore();
  const { setAllConfig } = useGlobalConfigStoreAllLanguage();
  useEffect(() => {
    setMounted(true);
  }, []);

  // Initialize i18n language from props or URL
  useEffect(() => {
    if (!mounted) return;

    const targetLocale = initialLocale || pathname.split('/').filter(Boolean)[0] || 'zh';

    const initI18n = async () => {
      const { resourcesCustom } = await loadLocaleMessages(targetLocale)
      setConfig(resourcesCustom[targetLocale as 'zh'].custom);
      setAllConfig(resourcesCustom);
      i18n.changeLanguage(targetLocale);
      document.cookie = `NEXT_LOCALE=${targetLocale}; path=/; max-age=31536000`;
      setLoaded(true)
    }
    initI18n();

    // Fallback: synchronize i18n language according to the URL
  }, [initialLocale, pathname, mounted]);

  if (!mounted || !loaded) {
    return null;
  }

  return <I18nextProvider i18n={i18n}>{children}</I18nextProvider>;
}
