import type { Metadata } from "next";
import { Inter } from "next/font/google";
import React, { ReactNode } from "react";
import { RootProvider } from "@/components/providers/rootProvider";
import { DeploymentProvider } from "@/components/providers/deploymentProvider";
import { ThemeProvider as NextThemesProvider } from "next-themes";
import { ClientLayout } from "./layout.client";
import I18nProviderWrapper from "@/components/providers/I18nProviderWrapper";

import "@/styles/globals.css";
import "@/styles/react-markdown.css";
import "github-markdown-css/github-markdown.css";
import "katex/dist/katex.min.css";

const inter = Inter({ subsets: ["latin"] });

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale?: string }>;
}): Promise<Metadata> {
  // Simple metadata for now - can be enhanced later with i18n
  return {
    title: "Nexent - AI Agent Platform",
    description:
      "A powerful AI agent platform for intelligent conversations and automation",
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

  return (
    <html lang="zh" suppressHydrationWarning>
      <body className={inter.className}>
        <NextThemesProvider
          attribute="class"
          defaultTheme="light"
          enableSystem
          disableTransitionOnChange
        >
          <I18nProviderWrapper locale={locale}>
            <DeploymentProvider>
              <RootProvider>
                <ClientLayout>{children}</ClientLayout>
              </RootProvider>
            </DeploymentProvider>
          </I18nProviderWrapper>
        </NextThemesProvider>
      </body>
    </html>
  );
}
