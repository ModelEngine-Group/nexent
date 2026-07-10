"use client";

import { useMemo, useState } from "react";
import { App, ConfigProvider, Input, Modal } from "antd";
import { motion } from "framer-motion";
import { Inbox, ShieldCheck, User, Zap } from "lucide-react";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import {
  useCreateSkillRepositoryListing,
  useInstallSkillFromRepository,
  useMyEditableSkills,
  useSkillRepositoryListingDetail,
  useSkillRepositoryListings,
  useUpdateSkillRepositoryStatus,
} from "@/hooks/skillRepository/useSkillRepositoryListings";
import { ApiError } from "@/services/api";
import { deleteSkillByName } from "@/services/skillService";
import { cn } from "@/lib/utils";
import type {
  MyEditableSkillItem,
  MySkillRepositoryInfoItem,
  SkillRepositoryListingItem,
  SkillRepositoryListingStatus,
} from "@/types/skillRepository";
import { CountBadge } from "./components/SkillRepositoryControls";
import { SkillRepositoryDetailModal } from "./components/SkillRepositoryDetailModal";
import { MineSkillsView } from "./components/MineSkillsView";
import { RepositoryView } from "./components/RepositoryView";
import { ReviewSkillList } from "./components/ReviewSkillList";
import { STATUS_LABELS } from "./components/skillRepositoryShared";
import SkillBuildModal from "../agents/components/agentConfig/SkillBuildModal";

enum SkillRepositoryTab {
  REPOSITORY = "repository",
  MINE = "mine",
  REVIEW = "review",
}

const REPOSITORY_PAGE_SIZE = 6;
const MINE_PAGE_SIZE = 6;
const REVIEW_PAGE_SIZE = 10;

const skillRepositoryTheme = {
  token: { colorPrimary: "#2563eb", colorInfo: "#3b82f6", borderRadius: 12 },
};

export default function SkillRepositoryPage() {
  const { pageVariants, pageTransition } = useSetupFlow();
  const { user } = useAuthorizationContext();
  const { message, modal } = App.useApp();
  const isAdmin = user?.role === USER_ROLES.ADMIN;

  const [tab, setTab] = useState<SkillRepositoryTab>(
    SkillRepositoryTab.REPOSITORY
  );
  const [repositoryPage, setRepositoryPage] = useState(1);
  const [repositorySearch, setRepositorySearch] = useState("");
  const [minePage, setMinePage] = useState(1);
  const [mineSearch, setMineSearch] = useState("");
  const [reviewPage, setReviewPage] = useState(1);
  const [detailRepositoryId, setDetailRepositoryId] = useState<number | null>(
    null
  );
  const [skillBuildOpen, setSkillBuildOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<MyEditableSkillItem | null>(
    null
  );
  const [copyListing, setCopyListing] =
    useState<SkillRepositoryListingItem | null>(null);
  const [copyTargetName, setCopyTargetName] = useState("");
  const [copyNameError, setCopyNameError] = useState<string | null>(null);

  const isRepositoryTab = tab === SkillRepositoryTab.REPOSITORY;
  const isMineTab = tab === SkillRepositoryTab.MINE;
  const isReviewTab = tab === SkillRepositoryTab.REVIEW;

  const repositoryParams = useMemo(
    () => ({
      status: "shared" as const,
      page: repositoryPage,
      page_size: REPOSITORY_PAGE_SIZE,
      ...(repositorySearch.trim() ? { search: repositorySearch.trim() } : {}),
    }),
    [repositoryPage, repositorySearch]
  );

  const mineParams = useMemo(
    () => ({
      ownership: "all" as const,
      page: minePage,
      page_size: MINE_PAGE_SIZE,
      ...(mineSearch.trim() ? { search: mineSearch.trim() } : {}),
      ...(!mineSearch.trim() ? { new_skill_padding: true } : {}),
    }),
    [minePage, mineSearch]
  );

  const reviewParams = useMemo(
    () => ({
      page: reviewPage,
      page_size: REVIEW_PAGE_SIZE,
      sort_by_update_time: true,
    }),
    [reviewPage]
  );

  const {
    data: repositoryData,
    isLoading: isRepositoryLoading,
    isError: isRepositoryError,
    isFetching: isRepositoryFetching,
    refetch: refetchRepository,
  } = useSkillRepositoryListings(repositoryParams, isRepositoryTab);

  const { data: repositoryCountData } = useSkillRepositoryListings(
    { status: "shared", page: 1, page_size: 1 },
    true
  );

  const {
    data: mineData,
    isLoading: isMineLoading,
    isError: isMineError,
    isFetching: isMineFetching,
    refetch: refetchMine,
  } = useMyEditableSkills(mineParams, isMineTab);

  const { data: mineCountData } = useMyEditableSkills(
    { page: 1, page_size: 1, ownership: "all" },
    true
  );

  const {
    data: reviewData,
    isLoading: isReviewLoading,
    isError: isReviewError,
    isFetching: isReviewFetching,
    refetch: refetchReview,
  } = useSkillRepositoryListings(reviewParams, isAdmin && isReviewTab);

  const { data: reviewCountData } = useSkillRepositoryListings(
    { status: "pending_review", page: 1, page_size: 1 },
    isAdmin
  );

  const installMutation = useInstallSkillFromRepository();
  const createListingMutation = useCreateSkillRepositoryListing();
  const updateStatusMutation = useUpdateSkillRepositoryStatus();
  const {
    data: detailData,
    isLoading: isDetailLoading,
    isError: isDetailError,
    isFetching: isDetailFetching,
    refetch: refetchDetail,
  } = useSkillRepositoryListingDetail(
    detailRepositoryId,
    detailRepositoryId != null
  );

  const repositoryItems = repositoryData?.items ?? [];
  const repositoryTotal = repositoryData?.pagination?.total ?? 0;
  const mineItems = mineData?.items ?? [];
  const mineTotal = mineData?.pagination?.total ?? 0;
  const mineCounts = mineData?.counts ?? { all: 0, created: 0, others: 0 };
  const reviewItems = reviewData?.items ?? [];
  const reviewTotal = reviewData?.pagination?.total ?? 0;
  const repositoryTabCount = repositoryCountData?.pagination?.total ?? 0;
  const mineTabCount = mineCountData?.counts?.all ?? 0;
  const pendingReviewCount = reviewCountData?.pagination?.total ?? 0;
  const updatingRepositoryId = updateStatusMutation.isPending
    ? (updateStatusMutation.variables?.skillRepositoryId ?? null)
    : null;
  const installingRepositoryId = installMutation.isPending
    ? (installMutation.variables?.skillRepositoryId ?? null)
    : null;

  const getDuplicateSkillNames = (error: unknown): string[] | null => {
    const detail =
      error instanceof Error && "detail" in error
        ? (error as { detail?: unknown }).detail
        : null;
    if (
      typeof detail !== "object" ||
      detail == null ||
      !("type" in detail) ||
      (detail as { type?: unknown }).type !== "skill_duplicate"
    ) {
      return null;
    }
    const duplicates = (detail as { duplicate_skills?: unknown })
      .duplicate_skills;
    return Array.isArray(duplicates)
      ? duplicates.filter((name): name is string => typeof name === "string")
      : [];
  };

  const openDetail = (listing: SkillRepositoryListingItem) => {
    setDetailRepositoryId(listing.skill_repository_id);
  };

  const handleInstall = (listing: SkillRepositoryListingItem) => {
    const baseName = listing.name?.trim() || "Skill";
    setCopyListing(listing);
    setCopyTargetName(`${baseName} 副本`);
    setCopyNameError(null);
  };

  const handleConfirmInstall = async () => {
    if (!copyListing) {
      return;
    }
    const targetName = copyTargetName.trim();
    if (!targetName) {
      setCopyNameError("请输入 Skill 名称");
      return;
    }
    try {
      setCopyNameError(null);
      const result = await installMutation.mutateAsync({
        skillRepositoryId: copyListing.skill_repository_id,
        targetName,
      });
      message.success(
        result.name ? `Skill 已复制为：${result.name}` : "Skill 复制成功"
      );
      setCopyListing(null);
      setCopyTargetName("");
    } catch (error) {
      const duplicateNames = getDuplicateSkillNames(error);
      if (duplicateNames) {
        setCopyNameError(
          duplicateNames.length > 0
            ? `当前租户已存在同名 Skill：${duplicateNames.join("、")}`
            : "当前租户已存在同名 Skill，请修改名称后再复制"
        );
        return;
      }
      message.error(error instanceof Error ? error.message : "Skill 复制失败");
    }
  };

  const handleUpdateStatus = async (
    listing: SkillRepositoryListingItem,
    status: SkillRepositoryListingStatus
  ) => {
    try {
      await updateStatusMutation.mutateAsync({
        skillRepositoryId: listing.skill_repository_id,
        status,
      });
      message.success(`已${STATUS_LABELS[status]}`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "状态更新失败");
    }
  };

  const handleSetNotShared = async (
    repositoryInfo: MySkillRepositoryInfoItem
  ) => {
    const wasShared = repositoryInfo.status === "shared";
    await updateStatusMutation.mutateAsync({
      skillRepositoryId: repositoryInfo.skill_repository_id,
      status: "not_shared",
    });
    message.success(wasShared ? "已下架" : "已撤回申请");
  };

  const getActiveRepositoryInfo = (skill?: MyEditableSkillItem | null) =>
    (skill?.repository_info ?? []).filter(
      (info) => info.status === "shared" || info.status === "pending_review"
    );

  const confirmEditListedSkill = async (
    skill: MyEditableSkillItem
  ): Promise<boolean> => {
    const activeInfo = getActiveRepositoryInfo(skill);
    if (activeInfo.length === 0) {
      return true;
    }

    const hasShared = activeInfo.some((info) => info.status === "shared");
    const confirmed = await new Promise<boolean>((resolve) => {
      modal.confirm({
        title: hasShared ? "保存后将自动下架" : "保存后将撤回审核",
        content: hasShared
          ? "该 Skill 已上架，保存修改后将自动下架，需要重新提交审核。"
          : "该 Skill 正在审核中，保存修改后将撤回审核，需要重新提交。",
        okText: "继续保存",
        cancelText: "取消",
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });
    if (!confirmed) {
      return false;
    }

    try {
      await Promise.all(
        activeInfo.map((info) =>
          updateStatusMutation.mutateAsync({
            skillRepositoryId: info.skill_repository_id,
            status: "not_shared",
          })
        )
      );
      return true;
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : "Failed to update listing status"
      );
      return false;
    }
  };

  const handleSkillBuildSuccess = async () => {
    await refetchMine().catch(() => {});
    setEditingSkill(null);
  };

  const confirmUpdateStatus = (
    listing: SkillRepositoryListingItem,
    status: SkillRepositoryListingStatus
  ) => {
    modal.confirm({
      title: `确认${STATUS_LABELS[status]}？`,
      content: listing.name,
      okText: "确认",
      cancelText: "取消",
      onOk: () => handleUpdateStatus(listing, status),
    });
  };

  const confirmTakeDown = (listing: SkillRepositoryListingItem) => {
    modal.confirm({
      title: "确认下架？",
      content: listing.name,
      okText: "下架",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: () => handleUpdateStatus(listing, "not_shared"),
    });
  };

  return (
    <ConfigProvider theme={skillRepositoryTheme}>
      <div className="flex h-full min-h-0 w-full min-w-0 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]">
          <motion.div
            initial="initial"
            animate="in"
            exit="out"
            variants={pageVariants}
            transition={pageTransition}
            className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 sm:py-10"
          >
            <div className="flex flex-col gap-6">
              <section className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex items-start gap-4">
                  <div className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary shadow-sm">
                    <Zap className="size-7" />
                  </div>
                  <div>
                    <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl dark:text-slate-100">
                      Skill 仓库
                    </h1>
                    <p className="mt-1 max-w-xl text-sm leading-relaxed text-slate-600 dark:text-slate-300">
                      浏览同租户共享仓库、管理你有权限的 Skill，并发布与审核
                    </p>
                  </div>
                </div>
              </section>

              <Tabs
                value={tab}
                onValueChange={(value) => setTab(value as SkillRepositoryTab)}
                className="w-full"
              >
                <TabsList
                  className={cn(
                    "mb-6 grid h-auto w-full gap-2 rounded-xl border border-border bg-secondary/60 px-2 py-2",
                    isAdmin ? "grid-cols-3" : "grid-cols-2"
                  )}
                >
                  <TabsTrigger
                    value={SkillRepositoryTab.REPOSITORY}
                    className="w-full justify-center gap-1.5 rounded-lg px-[5px] py-2 text-sm data-[state=active]:shadow-sm"
                  >
                    <Inbox className="size-4" aria-hidden />
                    仓库
                    <CountBadge count={repositoryTabCount} />
                  </TabsTrigger>
                  <TabsTrigger
                    value={SkillRepositoryTab.MINE}
                    className="w-full justify-center gap-1.5 rounded-lg px-[5px] py-2 text-sm data-[state=active]:shadow-sm"
                  >
                    <User className="size-4" aria-hidden />
                    我的 Skill
                    <CountBadge count={mineTabCount} />
                  </TabsTrigger>
                  {isAdmin ? (
                    <TabsTrigger
                      value={SkillRepositoryTab.REVIEW}
                      className="w-full justify-center gap-1.5 rounded-lg px-[5px] py-2 text-sm data-[state=active]:shadow-sm"
                    >
                      <ShieldCheck className="size-4" aria-hidden />
                      审核中心
                      <CountBadge count={pendingReviewCount} strong />
                    </TabsTrigger>
                  ) : null}
                </TabsList>
              </Tabs>

              {isRepositoryTab ? (
                <RepositoryView
                  searchQuery={repositorySearch}
                  onSearchChange={(value) => {
                    setRepositorySearch(value);
                    setRepositoryPage(1);
                  }}
                  listings={repositoryItems}
                  isLoading={isRepositoryLoading}
                  isError={isRepositoryError}
                  isFetching={isRepositoryFetching}
                  page={repositoryPage}
                  pageSize={REPOSITORY_PAGE_SIZE}
                  total={repositoryTotal}
                  onPageChange={setRepositoryPage}
                  onRetry={() => refetchRepository()}
                  onInstall={handleInstall}
                  onDetailClick={openDetail}
                  showAdminMenu={isAdmin}
                  onTakeDown={confirmTakeDown}
                  installingRepositoryId={installingRepositoryId}
                  takingDownRepositoryId={updatingRepositoryId}
                />
              ) : isMineTab ? (
                <MineSkillsView
                  skills={mineItems}
                  counts={mineCounts}
                  searchQuery={mineSearch}
                  onSearchChange={(value) => {
                    setMineSearch(value);
                    setMinePage(1);
                  }}
                  isLoading={isMineLoading}
                  isError={isMineError}
                  isFetching={isMineFetching}
                  page={minePage}
                  pageSize={MINE_PAGE_SIZE}
                  total={mineTotal}
                  onPageChange={setMinePage}
                  onRetry={() => refetchMine()}
                  onCreateSkill={() => {
                    setEditingSkill(null);
                    setSkillBuildOpen(true);
                  }}
                  onEditSkill={(skill) => {
                    setEditingSkill(skill);
                    setSkillBuildOpen(true);
                  }}
                  onDeleteSkill={async (skill) => {
                    const name = skill.name?.trim();
                    if (!name) {
                      message.error("Skill 名称为空，无法删除");
                      return;
                    }
                    const result = await deleteSkillByName(name);
                    if (!result.success) {
                      message.error(result.message || "删除失败");
                      throw new Error(result.message || "Delete skill failed");
                    }
                    message.success("删除成功");
                    await refetchMine();
                  }}
                  onApplyListing={async (skill, payload) => {
                    try {
                      await createListingMutation.mutateAsync({
                        skillId: skill.skill_id,
                        payload,
                      });
                      message.success("已提交上架申请");
                    } catch (error) {
                      if (
                        error instanceof ApiError &&
                        Number(error.code) === 403
                      ) {
                        message.error("当前账号只能启用自己创建的 Skill");
                        return;
                      }
                      message.error(
                        error instanceof Error ? error.message : "提交审批失败"
                      );
                    }
                  }}
                  isUpdatingStatus={updateStatusMutation.isPending}
                  onSetNotShared={handleSetNotShared}
                />
              ) : isReviewTab ? (
                <ReviewSkillList
                  listings={reviewItems}
                  isLoading={isReviewLoading}
                  isError={isReviewError}
                  isFetching={isReviewFetching}
                  page={reviewPage}
                  pageSize={REVIEW_PAGE_SIZE}
                  total={reviewTotal}
                  onPageChange={setReviewPage}
                  onRetry={() => refetchReview()}
                  updatingRepositoryId={updatingRepositoryId}
                  onDetailClick={openDetail}
                  onApprove={(listing) =>
                    confirmUpdateStatus(listing, "shared")
                  }
                  onReject={(listing) =>
                    confirmUpdateStatus(listing, "rejected")
                  }
                />
              ) : null}
            </div>
          </motion.div>
        </div>
      </div>

      <SkillRepositoryDetailModal
        open={detailRepositoryId != null}
        detail={detailData}
        isLoading={isDetailLoading}
        isError={isDetailError}
        isFetching={isDetailFetching}
        onClose={() => setDetailRepositoryId(null)}
        onRetry={() => refetchDetail()}
      />
      <Modal
        centered
        destroyOnHidden
        title="复制为我的 Skill"
        open={copyListing != null}
        okText="复制"
        cancelText="取消"
        confirmLoading={installMutation.isPending}
        onOk={handleConfirmInstall}
        onCancel={() => {
          setCopyListing(null);
          setCopyTargetName("");
          setCopyNameError(null);
        }}
      >
        <div className="space-y-2 pt-2">
          <label className="text-sm font-medium text-slate-700 dark:text-slate-200">
            Skill 名称
          </label>
          <Input
            value={copyTargetName}
            status={copyNameError ? "error" : undefined}
            placeholder="请输入 Skill 名称"
            maxLength={100}
            onChange={(event) => {
              setCopyTargetName(event.target.value);
              if (copyNameError) {
                setCopyNameError(null);
              }
            }}
            onPressEnter={handleConfirmInstall}
          />
          {copyNameError ? (
            <p className="text-sm text-red-500">{copyNameError}</p>
          ) : (
            <p className="text-sm text-slate-500">
              如果当前租户已存在同名 Skill，请修改名称后再复制。
            </p>
          )}
        </div>
      </Modal>
      <SkillBuildModal
        isOpen={skillBuildOpen}
        editingSkill={editingSkill}
        onCancel={() => {
          setSkillBuildOpen(false);
          setEditingSkill(null);
        }}
        onSuccess={handleSkillBuildSuccess}
        onBeforeEditSave={confirmEditListedSkill}
      />
    </ConfigProvider>
  );
}
