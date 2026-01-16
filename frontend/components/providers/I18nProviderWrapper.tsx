"use client";

import { ReactNode, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { I18nextProvider } from "react-i18next";

import i18n from "@/app/i18n";

interface I18nProviderWrapperProps {
  children: ReactNode;
  locale?: string;
}

export default function I18nProviderWrapper({
  children,
  locale: initialLocale,
}: I18nProviderWrapperProps) {
  const [mounted, setMounted] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    setMounted(true);
  }, []);

  // Initialize i18n language from props or URL
  useEffect(() => {
    if (!mounted) return;

    // If locale is provided via props, use it
    if (initialLocale && (initialLocale === "zh" || initialLocale === "en")) {
      if (i18n.language !== initialLocale) {
        i18n.changeLanguage(initialLocale);
      }
      document.cookie = `NEXT_LOCALE=${initialLocale}; path=/; max-age=31536000`;
      return;
    }

    // Fallback: synchronize i18n language according to the URL
    const segments = pathname.split("/").filter(Boolean);
    const urlLocale = segments[0];

    if (urlLocale === "zh" || urlLocale === "en") {
      if (i18n.language !== urlLocale) {
        i18n.changeLanguage(urlLocale);
      }
      document.cookie = `NEXT_LOCALE=${urlLocale}; path=/; max-age=31536000`;
    }
  }, [initialLocale, pathname, mounted]);

  if (!mounted) {
    return null;
  }

  return <I18nextProvider i18n={i18n}>{children}</I18nextProvider>;
}
