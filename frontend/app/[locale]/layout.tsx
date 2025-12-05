import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { ReactNode } from "react";
import path from "path";
import fs from "fs/promises";
import { RootProvider } from "@/components/providers";
import { ThemeProvider as NextThemesProvider } from "next-themes";
import I18nProviderWrapper from "@/components/providers/I18nProviderWrapper";

import "@/styles/globals.css";
import "@/styles/react-markdown.css";
import "github-markdown-css/github-markdown.css";
import "katex/dist/katex.min.css";
import log from "@/lib/logger";

const inter = Inter({ subsets: ["latin"] });

export async function generateMetadata(props: {
  params: Promise<{ locale?: string }>;
}): Promise<Metadata> {
  const { locale } = await props.params;
  const resolvedLocale = (["zh", "en"].includes(locale ?? "")
    ? locale
    : "zh") as "zh" | "en";
  let messages: any = {};

  if (["zh", "en"].includes(resolvedLocale)) {
    try {
      const filePath = path.join(
        process.cwd(),
        "public",
        "locales",
        resolvedLocale,
        "common.json"
      );
      const fileContent = await fs.readFile(filePath, "utf8");
      messages = JSON.parse(fileContent);
    } catch (error) {
      log.error(
        `Failed to load i18n messages for locale: ${resolvedLocale}`,
        error
      );
    }
  }

  return {
    title: {
      default: messages["mainPage.layout.title"],
      template: messages["mainPage.layout.titleTemplate"],
    },
    description: messages["mainPage.layout.description"],
    icons: {
      icon: "/favicon.png",
      shortcut: "/favicon.png",
      apple: "/favicon.png",
    },
  };
}

export default async function RootLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale?: string }>;
}) {
  const { locale } = await params;
  const resolvedLocale = (["zh", "en"].includes(locale ?? "")
    ? locale
    : "zh") as "zh" | "en";

  return (
    <html lang={resolvedLocale} suppressHydrationWarning>
      <body className={inter.className}>
        <NextThemesProvider
          attribute="class"
          defaultTheme="light"
          enableSystem
          disableTransitionOnChange
        >
          <I18nProviderWrapper>
            <RootProvider>{children}</RootProvider>
          </I18nProviderWrapper>
        </NextThemesProvider>
      </body>
    </html>
  );
}
