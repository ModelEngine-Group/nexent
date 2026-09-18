"use client";

import { ConfigProvider } from "antd";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Inbox, Puzzle, ShieldCheck, User } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import { McpToolsServicesTab } from "@/const/mcpTools";
import { McpRepository } from "./repository";
import { MyMcpServices } from "./my-mcp-services";
import { McpReviewCenter } from "./review-center";
import { useMcpSpaceController } from "./use-mcp-space-controller";

const mcpToolsTheme = {
  token: { colorPrimary: "#2563eb", colorInfo: "#0284c7" },
};

export default function McpToolsPage() {
  const { t } = useTranslation("common");
  const { pageVariants, pageTransition } = useSetupFlow();
  const controller = useMcpSpaceController();
  const {
    tab,
    setTab,
    isAdmin,
    repositoryCount,
    mineCount,
    pendingReviewCount,
  } = controller;

  return (
    <ConfigProvider theme={mcpToolsTheme}>
      <div className="flex h-full min-h-0 w-full min-w-0 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]">
          <motion.div
            initial="initial"
            animate="in"
            exit="out"
            variants={pageVariants}
            transition={pageTransition}
            className="w-full h-full px-4 py-8 sm:px-6 sm:py-10 xl:px-16"
          >
            <div className="flex flex-col gap-6">
              <section className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex items-start gap-4">
                  <div className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary shadow-sm">
                    <Puzzle className="size-7" />
                  </div>
                  <div>
                    <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl dark:text-slate-100">
                      {t("mcpTools.page.title")}
                    </h1>
                    <p className="mt-1 max-w-xl text-sm leading-relaxed text-slate-600 dark:text-slate-300">
                      {t("mcpTools.page.subtitle")}
                    </p>
                  </div>
                </div>
              </section>

              <Tabs
                value={tab}
                onValueChange={(value) => setTab(value as McpToolsServicesTab)}
                className="w-full"
              >
                <TabsList className="flex h-auto w-full justify-start gap-6 overflow-x-auto rounded-none border-b border-slate-200 bg-transparent p-0 dark:border-slate-700">
                  <TabsTrigger
                    value={McpToolsServicesTab.REPOSITORY}
                    className="shrink-0 gap-1.5 rounded-none border-b-2 border-transparent px-1 py-2 text-sm text-slate-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none dark:data-[state=active]:bg-transparent"
                  >
                    <Inbox className="size-4" aria-hidden />
                    {t("repository.page.tab.repository")}
                    <span className="ml-1 rounded-md bg-background/70 px-1.5 text-xs text-muted-foreground">
                      {repositoryCount}
                    </span>
                  </TabsTrigger>
                  <TabsTrigger
                    value={McpToolsServicesTab.MINE}
                    className="shrink-0 gap-1.5 rounded-none border-b-2 border-transparent px-1 py-2 text-sm text-slate-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none dark:data-[state=active]:bg-transparent"
                  >
                    <User className="size-4" aria-hidden />
                    {t("mcpTools.page.tab.mine")}
                    <span className="ml-1 rounded-md bg-background/70 px-1.5 text-xs text-muted-foreground">
                      {mineCount}
                    </span>
                  </TabsTrigger>
                  {isAdmin ? (
                    <TabsTrigger
                      value={McpToolsServicesTab.REVIEW}
                      className="shrink-0 gap-1.5 rounded-none border-b-2 border-transparent px-1 py-2 text-sm text-slate-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none dark:data-[state=active]:bg-transparent"
                    >
                      <ShieldCheck className="size-4" aria-hidden />
                      {t("repository.page.tab.review")}
                      {pendingReviewCount > 0 ? (
                        <span className="ml-1 inline-flex size-5 items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
                          {pendingReviewCount}
                        </span>
                      ) : null}
                    </TabsTrigger>
                  ) : null}
                </TabsList>
              </Tabs>

              {tab === McpToolsServicesTab.REPOSITORY ? (
                <McpRepository {...controller.repositoryProps} />
              ) : null}
              {tab === McpToolsServicesTab.MINE ? (
                <MyMcpServices {...controller.mineProps} />
              ) : null}
              {tab === McpToolsServicesTab.REVIEW && isAdmin ? (
                <McpReviewCenter {...controller.reviewProps} />
              ) : null}

              {controller.dialogs}
            </div>
          </motion.div>
        </div>
      </div>
    </ConfigProvider>
  );
}
