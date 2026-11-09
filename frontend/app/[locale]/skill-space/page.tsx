// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useState } from "react";
import { ConfigProvider } from "antd";
import { motion } from "framer-motion";
import { Inbox, ShieldCheck, User, Zap } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import {
  useMyEditableSkillCounts,
  useSkillRepositoryListings,
} from "@/hooks/skillRepository/useSkillRepositoryListings";
import { CountBadge } from "./components/SkillRepositoryControls";
import { SkillSpace } from "./skill-space";
import { MySkill } from "./my-skill";
import { ReviewCenter } from "./review-center";

enum SkillRepositoryTab {
  REPOSITORY = "repository",
  MINE = "mine",
  REVIEW = "review",
}

const skillRepositoryTheme = {
  token: { colorPrimary: "#2563eb", colorInfo: "#3b82f6" },
};

export default function SkillRepositoryPage() {
  const { t } = useTranslation("common");
  const { pageVariants, pageTransition } = useSetupFlow();
  const searchParams = useSearchParams();
  const { user, hasPermission } = useAuthorizationContext();
  const managed = user?.casdoorFeaturePolicy === true;
  const canBrowse = !managed || hasPermission("skill.repository:read");
  const canCreateSkill = !managed || hasPermission("skill:create");
  const canPublish = !managed || hasPermission("skill.repository:publish");
  const canUseMine = canCreateSkill || canPublish;
  const canReview = managed
    ? hasPermission("skill.repository:review")
    : user?.role === USER_ROLES.ADMIN;
  const [tab, setTab] = useState<SkillRepositoryTab>(
    SkillRepositoryTab.REPOSITORY
  );

  useEffect(() => {
    const tabParam = searchParams.get("tab");
    /* eslint-disable react-hooks/set-state-in-effect -- URL changes select the requested tab. */
    if (tabParam === SkillRepositoryTab.MINE) {
      setTab(SkillRepositoryTab.MINE);
    } else if (tabParam === SkillRepositoryTab.REPOSITORY) {
      setTab(SkillRepositoryTab.REPOSITORY);
    } else if (tabParam === SkillRepositoryTab.REVIEW && canReview) {
      setTab(SkillRepositoryTab.REVIEW);
    }
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [searchParams, canReview]);

  const visibleTabs = [
    ...(canBrowse ? [SkillRepositoryTab.REPOSITORY] : []),
    ...(canUseMine ? [SkillRepositoryTab.MINE] : []),
    ...(canReview ? [SkillRepositoryTab.REVIEW] : []),
  ];
  const activeTab = visibleTabs.includes(tab) ? tab : visibleTabs[0];

  const { data: repositoryCountData } = useSkillRepositoryListings(
    { status: "shared", page: 1, page_size: 1 },
    canBrowse
  );
  const { data: mineCountData } = useMyEditableSkillCounts(canUseMine);
  const { data: reviewCountData } = useSkillRepositoryListings(
    { status: "pending_review", page: 1, page_size: 1 },
    canReview
  );
  const repositoryTabCount = repositoryCountData?.pagination?.total ?? 0;
  const mineTabCount = mineCountData?.counts?.all ?? 0;
  const pendingReviewCount = reviewCountData?.pagination?.total ?? 0;
  const isRepositoryTab = activeTab === SkillRepositoryTab.REPOSITORY;
  const isMineTab = activeTab === SkillRepositoryTab.MINE;
  const isReviewTab = activeTab === SkillRepositoryTab.REVIEW;

  return (
    <ConfigProvider theme={skillRepositoryTheme}>
      <div className="flex h-full min-h-0 w-full min-w-0 flex-col">
        <div className="min-h-0 flex-1 overflow-hidden">
          <motion.div
            initial="initial"
            animate="in"
            exit="out"
            variants={pageVariants}
            transition={pageTransition}
            className="flex h-full min-h-0 w-full flex-col px-4 py-8 sm:px-6 sm:py-10 xl:px-16"
          >
            <div className="flex min-h-0 flex-1 flex-col gap-6">
              <section className="flex shrink-0 flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex items-start gap-4">
                  <div className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary shadow-sm">
                    <Zap className="size-7" />
                  </div>
                  <div>
                    <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl dark:text-slate-100">
                      {t("skillRepository.page.title")}
                    </h1>
                    <p className="mt-1 max-w-xl text-sm leading-relaxed text-slate-600 dark:text-slate-300">
                      {t("skillRepository.page.subtitle")}
                    </p>
                  </div>
                </div>
              </section>

              <Tabs
                value={activeTab ?? ""}
                onValueChange={(value) => setTab(value as SkillRepositoryTab)}
                className="w-full shrink-0"
              >
                <TabsList className="flex h-auto w-full justify-start gap-6 overflow-x-auto rounded-none border-b border-slate-200 bg-transparent p-0 dark:border-slate-700">
                  {canBrowse && (
                    <TabsTrigger
                      value={SkillRepositoryTab.REPOSITORY}
                      className="shrink-0 gap-1.5 rounded-none border-b-2 border-transparent px-1 py-2 text-sm text-slate-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none dark:data-[state=active]:bg-transparent"
                    >
                      <Inbox className="size-4" aria-hidden />
                      {t("repository.page.tab.repository")}
                      <CountBadge count={repositoryTabCount} />
                    </TabsTrigger>
                  )}
                  {canUseMine && (
                    <TabsTrigger
                      value={SkillRepositoryTab.MINE}
                      className="shrink-0 gap-1.5 rounded-none border-b-2 border-transparent px-1 py-2 text-sm text-slate-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none dark:data-[state=active]:bg-transparent"
                    >
                      <User className="size-4" aria-hidden />
                      {t("skillRepository.page.tab.mine")}
                      <CountBadge count={mineTabCount} />
                    </TabsTrigger>
                  )}
                  {canReview ? (
                    <TabsTrigger
                      value={SkillRepositoryTab.REVIEW}
                      className="shrink-0 gap-1.5 rounded-none border-b-2 border-transparent px-1 py-2 text-sm text-slate-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none dark:data-[state=active]:bg-transparent"
                    >
                      <ShieldCheck className="size-4" aria-hidden />
                      {t("repository.page.tab.review")}
                      <CountBadge count={pendingReviewCount} strong />
                    </TabsTrigger>
                  ) : null}
                </TabsList>
              </Tabs>

              <div
                data-testid="repository-tab-content"
                className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-px pb-1 [scrollbar-gutter:stable]"
              >
                {canBrowse && <SkillSpace active={isRepositoryTab} />}
                {canUseMine && (
                  <MySkill
                    active={isMineTab}
                    canCreate={canCreateSkill}
                    canPublish={canPublish}
                  />
                )}
                {canReview && <ReviewCenter active={isReviewTab} />}
              </div>
            </div>
          </motion.div>
        </div>
      </div>
    </ConfigProvider>
  );
}
