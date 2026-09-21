"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ConfigProvider } from "antd";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Bot, Inbox, ShieldCheck, User } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import {
  useAgentRepositoryListings,
  useMyEditableAgents,
} from "@/hooks/agentRepository/useAgentRepositoryListings";
import { AgentSpace } from "./agent-space";
import { MyAgent } from "./my-agent";
import { ReviewCenter } from "./review-center";

enum AgentRepositoryTab {
  REPOSITORY = "repository",
  MINE = "mine",
  REVIEW = "review",
}

const agentRepositoryTheme = {
  token: { colorPrimary: "#2563eb", colorInfo: "#3b82f6" },
};

export default function AgentRepositoryPage() {
  const { t } = useTranslation("common");
  const { pageVariants, pageTransition } = useSetupFlow();
  const searchParams = useSearchParams();
  const { user } = useAuthorizationContext();
  const isAdmin = user?.role === USER_ROLES.ADMIN;
  const [tab, setTab] = useState<AgentRepositoryTab>(() => {
    const backTab = searchParams.get("back_tab");
    if (backTab === "mine") return AgentRepositoryTab.MINE;
    if (backTab === "repository") return AgentRepositoryTab.REPOSITORY;
    if (backTab === "review") return AgentRepositoryTab.REVIEW;
    return AgentRepositoryTab.REPOSITORY;
  });

  useEffect(() => {
    const tabParam = searchParams.get("tab");
    /* eslint-disable react-hooks/set-state-in-effect -- URL changes must update the selected tab. */
    if (tabParam === AgentRepositoryTab.MINE) {
      setTab(AgentRepositoryTab.MINE);
      return;
    }
    if (tabParam === AgentRepositoryTab.REPOSITORY) {
      setTab(AgentRepositoryTab.REPOSITORY);
      return;
    }
    if (tabParam === AgentRepositoryTab.REVIEW && isAdmin) {
      setTab(AgentRepositoryTab.REVIEW);
    }
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [searchParams, isAdmin]);

  const isRepositoryTab = tab === AgentRepositoryTab.REPOSITORY;
  const isReviewTab = tab === AgentRepositoryTab.REVIEW && isAdmin;
  const isMineTab = tab === AgentRepositoryTab.MINE;
  const { data: repositoryCountData } = useAgentRepositoryListings(
    { status: "shared", page: 1, page_size: 1 },
    true
  );
  const { data: mineCountData } = useMyEditableAgents(
    { page: 1, page_size: 1, ownership: "all" },
    true
  );
  const { data: reviewCountData } = useAgentRepositoryListings(
    { status: "pending_review", page: 1, page_size: 1 },
    isAdmin
  );
  const repositoryTabCount = repositoryCountData?.pagination?.total ?? 0;
  const mineTabCount = mineCountData?.counts?.all ?? 0;
  const pendingReviewCount = reviewCountData?.pagination?.total ?? 0;

  return (
    <ConfigProvider theme={agentRepositoryTheme}>
      <div className="flex h-full min-h-0 w-full min-w-0 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]">
          <motion.div
            initial="initial"
            animate="in"
            exit="out"
            variants={pageVariants}
            transition={pageTransition}
            className="w-full px-4 py-8 sm:px-6 sm:py-10 xl:px-16"
          >
            <div className="flex flex-col gap-6">
              <section className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex items-start gap-4">
                  <div className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary shadow-sm">
                    <Bot className="size-7" />
                  </div>
                  <div>
                    <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl dark:text-slate-100">
                      {t("agentRepository.page.title")}
                    </h1>
                    <p className="mt-1 max-w-xl text-sm leading-relaxed text-slate-600 dark:text-slate-300">
                      {t("agentRepository.page.subtitle")}
                    </p>
                  </div>
                </div>
              </section>

              <Tabs
                value={tab}
                onValueChange={(value) => setTab(value as AgentRepositoryTab)}
                className="w-full"
              >
                <TabsList className="flex h-auto w-full justify-start gap-6 overflow-x-auto rounded-none border-b border-slate-200 bg-transparent p-0 dark:border-slate-700">
                  <TabsTrigger
                    value={AgentRepositoryTab.REPOSITORY}
                    className="shrink-0 gap-1.5 rounded-none border-b-2 border-transparent px-1 py-2 text-sm text-slate-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none dark:data-[state=active]:bg-transparent"
                  >
                    <Inbox className="size-4" aria-hidden />
                    {t("repository.page.tab.repository")}
                    <span className="ml-1 rounded-md bg-background/70 px-1.5 text-xs text-muted-foreground">
                      {repositoryTabCount}
                    </span>
                  </TabsTrigger>
                  <TabsTrigger
                    value={AgentRepositoryTab.MINE}
                    className="shrink-0 gap-1.5 rounded-none border-b-2 border-transparent px-1 py-2 text-sm text-slate-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none dark:data-[state=active]:bg-transparent"
                  >
                    <User className="size-4" aria-hidden />
                    {t("agentRepository.page.tab.mine")}
                    <span className="ml-1 rounded-md bg-background/70 px-1.5 text-xs text-muted-foreground">
                      {mineTabCount}
                    </span>
                  </TabsTrigger>
                  {isAdmin ? (
                    <TabsTrigger
                      value={AgentRepositoryTab.REVIEW}
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

              <div hidden={!isRepositoryTab}>
                <AgentSpace active={isRepositoryTab} />
              </div>
              {isAdmin ? (
                <div hidden={!isReviewTab}>
                  <ReviewCenter active={isReviewTab} />
                </div>
              ) : null}
              <div hidden={!isMineTab}>
                <MyAgent active={isMineTab} />
              </div>
            </div>
          </motion.div>
        </div>
      </div>
    </ConfigProvider>
  );
}
