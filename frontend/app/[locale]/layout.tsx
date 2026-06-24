import type { Metadata } from "next";
import { Inter, Ma_Shan_Zheng } from "next/font/google";
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

const inter = Inter({ subsets: ["latin"] });
const hospitalTitleFont = Ma_Shan_Zheng({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-hospital-title",
  display: "swap",
});

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale?: string }>;
}): Promise<Metadata> {
  // Simple metadata for now - can be enhanced later with i18n
  return {
    title: "省医智擎 - AI 医疗助手平台",
    description:
      "强大的 AI 医疗助手平台，提供智能对话和自动化服务",
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
      <body className={`${inter.className} ${hospitalTitleFont.variable}`}>
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
