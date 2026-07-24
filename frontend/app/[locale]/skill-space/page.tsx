"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { App, ConfigProvider, Input, Modal } from "antd";
import { motion } from "framer-motion";
import { Inbox, ShieldCheck, User, Zap } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";

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
import { parseSkillReviewDeepLinkParams } from "@/lib/notificationNavigation";
import { ApiError } from "@/services/api";
import { deleteSkillByName } from "@/services/skillService";
import { cn } from "@/lib/utils";
import type {
  MineOwnershipFilter,
  MyEditableSkillItem,
  MySkillRepositoryInfoItem,
  SkillRepositoryListingItem,
  SkillRepositoryListingStatus,
} from "@/types/skillRepository";
import type { Skill } from "@/types/agentConfig";
import { CountBadge } from "./components/SkillRepositoryControls";
import { SkillRepositoryDetailModal } from "./components/SkillRepositoryDetailModal";
import { MineSkillsView } from "./components/MineSkillsView";
import { RepositoryView } from "./components/RepositoryView";
import { ReviewSkillList } from "./components/ReviewSkillList";
import {
  SkillRepositoryReviewConfirmModal,
  type SkillRepositoryReviewAction,
} from "./components/SkillRepositoryReviewConfirmModal";
import {
  getSkillRepositoryStatusLabel,
} from "./components/skillRepositoryShared";
import SkillBuildModal from "../agents/components/agentConfig/SkillBuildModal";
import SkillDetailModal from "../agents/components/agentConfig/SkillDetailModal";

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

const STATUS_ACTION_LABEL_KEYS: Partial<
  Record<SkillRepositoryListingStatus, string>
> = {
  not_shared: "skillRepository.action.status.notShared",
  shared: "skillRepository.action.status.shared",
  rejected: "skillRepository.action.status.rejected",
};

export default function SkillRepositoryPage() {
  const { t } = useTranslation("common");
  const { pageVariants, pageTransition } = useSetupFlow();
  const searchParams = useSearchParams();
  const router = useRouter();
  const params = useParams<{ locale: string }>();
  const locale = params.locale || "en";
  const { user } = useAuthorizationContext();
  const { message, modal } = App.useApp();
  const isAdmin = user?.role === USER_ROLES.ADMIN;

  const [tab, setTab] = useState<SkillRepositoryTab>(
    SkillRepositoryTab.REPOSITORY
  );
  const [repositoryPage, setRepositoryPage] = useState(1);
  const [repositorySearch, setRepositorySearch] = useState("");
  const [minePage, setMinePage] = useState(1);
  const [mineOwnership, setMineOwnership] =
    useState<MineOwnershipFilter>("all");
  const [mineSearch, setMineSearch] = useState("");
  const [reviewPage, setReviewPage] = useState(1);
  const [detailRepositoryId, setDetailRepositoryId] = useState<number | null>(
    null
  );
  const [skillBuildOpen, setSkillBuildOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<MyEditableSkillItem | null>(
    null
  );
  const [viewingSkill, setViewingSkill] = useState<MyEditableSkillItem | null>(
    null
  );
  const [copyListing, setCopyListing] =
    useState<SkillRepositoryListingItem | null>(null);
  const [copyTargetName, setCopyTargetName] = useState("");
  const [copyNameError, setCopyNameError] = useState<string | null>(null);
  const [reviewListing, setReviewListing] =
    useState<SkillRepositoryListingItem | null>(null);
  const [reviewAction, setReviewAction] =
    useState<SkillRepositoryReviewAction | null>(null);

  useEffect(() => {
    const tabParam = searchParams.get("tab");
    if (tabParam === SkillRepositoryTab.MINE) {
      setTab(SkillRepositoryTab.MINE);
      return;
    }
    if (tabParam === SkillRepositoryTab.REPOSITORY) {
      setTab(SkillRepositoryTab.REPOSITORY);
      return;
    }
    if (tabParam === SkillRepositoryTab.REVIEW && isAdmin) {
      setTab(SkillRepositoryTab.REVIEW);
    }
  }, [searchParams, isAdmin]);

  const isRepositoryTab = tab === SkillRepositoryTab.REPOSITORY;
  const isMineTab = tab === SkillRepositoryTab.MINE;
  const isReviewTab = tab === SkillRepositoryTab.REVIEW;

  const reviewDeepLink = useMemo(
    () => parseSkillReviewDeepLinkParams(searchParams),
    [searchParams]
  );

  const handleReviewDeepLinkConsumed = useCallback(() => {
    router.replace(`/${locale}/skill-space?tab=mine`);
  }, [locale, router]);

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
      ownership: mineOwnership,
      page: minePage,
      page_size: MINE_PAGE_SIZE,
      ...(mineSearch.trim() ? { search: mineSearch.trim() } : {}),
      ...(mineOwnership === "all" && !mineSearch.trim()
        ? { new_skill_padding: true }
        : {}),
    }),
    [mineOwnership, minePage, mineSearch]
  );

  const reviewParams = useMemo(
    () => ({
      status: "pending_review" as const,
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

  const {
    data: deepLinkMineData,
    isLoading: isDeepLinkMineLoading,
  } = useMyEditableSkills(
    {
      ownership: "all",
      page: 1,
      page_size: 100,
      new_skill_padding: false,
    },
    isMineTab && reviewDeepLink != null
  );

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

  useEffect(() => {
    const refreshActiveTab = async () => {
      if (tab === SkillRepositoryTab.REPOSITORY) {
        await refetchRepository();
      } else if (tab === SkillRepositoryTab.MINE) {
        await refetchMine();
      } else if (tab === SkillRepositoryTab.REVIEW) {
        await refetchReview();
      }
    };

    refreshActiveTab().catch(() => {});
  }, [tab, refetchRepository, refetchMine, refetchReview]);

  const repositoryItems = repositoryData?.items ?? [];
  const repositoryTotal = repositoryData?.pagination?.total ?? 0;
  const mineItems = mineData?.items ?? [];
  const mineTotal = mineData?.pagination?.total ?? 0;
  const mineCounts = mineData?.counts ?? { all: 0, created: 0, others: 0 };
  const deepLinkFallbackSkill = useMemo(() => {
    if (!reviewDeepLink) {
      return null;
    }
    const items = deepLinkMineData?.items ?? [];
    return (
      items.find(
        (item): item is MyEditableSkillItem =>
          !("new_skill_padding" in item && item.new_skill_padding) &&
          item.skill_id === reviewDeepLink.skillId
      ) ?? null
    );
  }, [deepLinkMineData?.items, reviewDeepLink]);
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
    setCopyTargetName(
      t("skillRepository.copy.defaultName", { name: baseName })
    );
    setCopyNameError(null);
  };

  const handleConfirmInstall = async () => {
    if (!copyListing) {
      return;
    }
    const targetName = copyTargetName.trim();
    if (!targetName) {
      setCopyNameError(t("skillRepository.copy.nameRequired"));
      return;
    }
    try {
      setCopyNameError(null);
      const result = await installMutation.mutateAsync({
        skillRepositoryId: copyListing.skill_repository_id,
        targetName,
      });
      message.success(
        result.name
          ? t("skillRepository.copy.successWithName", { name: result.name })
          : t("skillRepository.copy.success")
      );
      setCopyListing(null);
      setCopyTargetName("");
    } catch (error) {
      const duplicateNames = getDuplicateSkillNames(error);
      if (duplicateNames) {
        setCopyNameError(
          duplicateNames.length > 0
            ? t("skillRepository.copy.duplicateWithNames", {
                names: duplicateNames.join("、"),
              })
            : t("skillRepository.copy.duplicate")
        );
        return;
      }
      message.error(
        error instanceof Error
          ? error.message
          : t("skillRepository.copy.failed")
      );
    }
  };

  const handleUpdateStatus = async (
    listing: SkillRepositoryListingItem,
    status: SkillRepositoryListingStatus,
    content?: string
  ) => {
    try {
      await updateStatusMutation.mutateAsync({
        skillRepositoryId: listing.skill_repository_id,
        status,
        content,
      });
      message.success(
        t("skillRepository.action.success", {
          action: STATUS_ACTION_LABEL_KEYS[status]
            ? t(STATUS_ACTION_LABEL_KEYS[status])
            : getSkillRepositoryStatusLabel(t, status),
        })
      );
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("skillRepository.common.statusUpdateFailed")
      );
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
    message.success(
      wasShared
        ? t("skillRepository.mine.takeDownSuccess")
        : t("skillRepository.mine.withdrawSuccess")
    );
  };

  const handleSkillBuildSuccess = async () => {
    await refetchMine().catch(() => {});
    setEditingSkill(null);
  };

  const openReviewConfirmModal = (
    listing: SkillRepositoryListingItem,
    action: SkillRepositoryReviewAction
  ) => {
    setReviewListing(listing);
    setReviewAction(action);
  };

  const closeReviewConfirmModal = () => {
    setReviewListing(null);
    setReviewAction(null);
  };

  const confirmTakeDown = (listing: SkillRepositoryListingItem) => {
    modal.confirm({
      title: t("skillRepository.action.confirmTakeDown"),
      content: listing.name,
      okText: t("skillRepository.action.status.notShared"),
      cancelText: t("common.cancel"),
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
                      {t("skillRepository.page.title")}
                    </h1>
                    <p className="mt-1 max-w-xl text-sm leading-relaxed text-slate-600 dark:text-slate-300">
                      {t("skillRepository.page.subtitle")}
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
                    {t("skillRepository.page.tab.repository")}
                    <CountBadge count={repositoryTabCount} />
                  </TabsTrigger>
                  <TabsTrigger
                    value={SkillRepositoryTab.MINE}
                    className="w-full justify-center gap-1.5 rounded-lg px-[5px] py-2 text-sm data-[state=active]:shadow-sm"
                  >
                    <User className="size-4" aria-hidden />
                    {t("skillRepository.page.tab.mine")}
                    <CountBadge count={mineTabCount} />
                  </TabsTrigger>
                  {isAdmin ? (
                    <TabsTrigger
                      value={SkillRepositoryTab.REVIEW}
                      className="w-full justify-center gap-1.5 rounded-lg px-[5px] py-2 text-sm data-[state=active]:shadow-sm"
                    >
                      <ShieldCheck className="size-4" aria-hidden />
                      {t("skillRepository.page.tab.review")}
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
                  ownership={mineOwnership}
                  onOwnershipChange={(ownership) => {
                    setMineOwnership(ownership);
                    setMinePage(1);
                  }}
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
                  onViewSkill={(skill) => setViewingSkill(skill)}
                  onDeleteSkill={async (skill) => {
                    const name = skill.name?.trim();
                    if (!name) {
                      message.error(t("skillRepository.delete.emptyName"));
                      return;
                    }
                    const result = await deleteSkillByName(name);
                    if (!result.success) {
                      message.error(
                        result.message || t("skillRepository.delete.failed")
                      );
                      throw new Error(result.message || "Delete skill failed");
                    }
                    message.success(t("skillRepository.delete.success"));
                    await refetchMine();
                  }}
                  onApplyListing={async (skill, payload) => {
                    try {
                      await createListingMutation.mutateAsync({
                        skillId: skill.skill_id,
                        payload,
                      });
                      message.success(t("skillRepository.mine.applySuccess"));
                    } catch (error) {
                      if (
                        error instanceof ApiError &&
                        Number(error.code) === 403
                      ) {
                        message.error(t("skillRepository.mine.applyForbidden"));
                        return;
                      }
                      message.error(
                        error instanceof Error
                          ? error.message
                          : t("skillRepository.mine.applyError")
                      );
                    }
                  }}
                  isUpdatingStatus={updateStatusMutation.isPending}
                  onSetNotShared={handleSetNotShared}
                  reviewDeepLink={reviewDeepLink}
                  deepLinkFallbackSkill={deepLinkFallbackSkill}
                  deepLinkFallbackLoading={isDeepLinkMineLoading}
                  onReviewDeepLinkConsumed={handleReviewDeepLinkConsumed}
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
                    openReviewConfirmModal(listing, "approve")
                  }
                  onReject={(listing) =>
                    openReviewConfirmModal(listing, "reject")
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
        title={t("skillRepository.copy.title")}
        open={copyListing != null}
        okText={t("skillRepository.copy.confirm")}
        cancelText={t("common.cancel")}
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
            {t("skillRepository.copy.nameLabel")}
          </label>
          <Input
            value={copyTargetName}
            status={copyNameError ? "error" : undefined}
            placeholder={t("skillRepository.copy.namePlaceholder")}
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
              {t("skillRepository.copy.renameHint")}
            </p>
          )}
        </div>
      </Modal>
      <SkillRepositoryReviewConfirmModal
        open={reviewAction != null && reviewListing != null}
        action={reviewAction}
        listing={reviewListing}
        loading={updateStatusMutation.isPending}
        onClose={closeReviewConfirmModal}
        onConfirm={async (content) => {
          if (!reviewListing || !reviewAction) {
            return;
          }
          await handleUpdateStatus(
            reviewListing,
            reviewAction === "approve" ? "shared" : "rejected",
            content
          );
          closeReviewConfirmModal();
        }}
      />
      <SkillBuildModal
        isOpen={skillBuildOpen}
        editingSkill={editingSkill}
        onCancel={() => {
          setSkillBuildOpen(false);
          setEditingSkill(null);
        }}
        onSuccess={handleSkillBuildSuccess}
      />
      <SkillDetailModal
        open={viewingSkill != null}
        skill={
          viewingSkill
            ? ({
                skill_id: viewingSkill.skill_id,
                name: viewingSkill.name || "",
                description: viewingSkill.description || "",
                source: viewingSkill.source || "custom",
                tags: viewingSkill.tags || [],
              } satisfies Skill)
            : null
        }
        onClose={() => setViewingSkill(null)}
      />
    </ConfigProvider>
  );
}
