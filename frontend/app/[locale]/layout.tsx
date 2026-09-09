import type { Metadata } from "next";
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
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale?: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const isZh = locale === "zh";
  return {
    title: `AI Agent Platform`,
    description: isZh
      ? "一个强大的 AI 智能体平台，支持智能对话与流程自动化"
      : "A powerful AI agent platform for intelligent conversations and automation",
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
      <body className="font-sans">
        <NextThemesProvider
          attribute="class"
          defaultTheme="light"
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
