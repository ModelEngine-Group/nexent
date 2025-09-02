import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { ReactNode } from "react";
import path from "path";
import fs from "fs/promises";
import { ThemeProvider, RootProvider } from "@/components/providers";
import I18nProviderWrapper from "@/components/providers/I18nProviderWrapper";

import "@/styles/globals.css";

const inter = Inter({ subsets: ["latin"] });

export async function generateMetadata(props: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await props.params;
  let messages: any = {};

  if (["zh", "en"].includes(locale)) {
    try {
      const filePath = path.join(
        process.cwd(),
        "public",
        "locales",
        locale,
        "common.json"
      );
      const fileContent = await fs.readFile(filePath, "utf8");
      messages = JSON.parse(fileContent);
    } catch (error) {
      console.error(
        `Failed to load i18n messages for locale: ${locale}`,
        error
      );
    }
  }

  return {
    title: {
      default: messages.layout?.title ?? "Default Title",
      template: messages.layout?.titleTemplate ?? "%s | Default Site",
    },
    description: messages.layout?.description ?? "Default description",
    icons: {
      icon: "/modelengine-logo.png",
      shortcut: "/favicon.ico",
      apple: "/apple-touch-icon.png",
    },
  };
}

export default async function RootLayout(props: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { children, params } = props;
  const { locale } = await params;

  return (
    <html lang={locale} suppressHydrationWarning>
      <head>
        <link rel="icon" href="/modelengine-logo.png" sizes="any" />
      </head>
      <body className={inter.className}>
        <ThemeProvider
          attribute="class"
          defaultTheme="light"
          enableSystem
          disableTransitionOnChange
        >
          <I18nProviderWrapper>
            <RootProvider>{children}</RootProvider>
          </I18nProviderWrapper>
        </ThemeProvider>
      </body>
    </html>
  );
}
