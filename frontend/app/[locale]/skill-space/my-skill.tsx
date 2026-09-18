"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { App } from "antd";
import dynamic from "next/dynamic";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";
import type { TagResourcePredicate } from "@/types/tagManagement";
import {
  invalidateSkillRepositoryCaches,
  SKILLS_LIST_QUERY_KEY,
  useCreateSkillRepositoryListing,
  useMyEditableSkills,
  useUpdateSkillRepositoryStatus,
} from "@/hooks/skillRepository/useSkillRepositoryListings";
import { parseSkillReviewDeepLinkParams } from "@/lib/notificationNavigation";
import { ApiError } from "@/services/api";
import { deleteSkillByName } from "@/services/skillService";
import type {
  MineOwnershipFilter,
  MyEditableSkillItem,
  MySkillRepositoryInfoItem,
} from "@/types/skillRepository";
import type { Skill } from "@/types/agentConfig";
import {
  isNewSkillPaddingItem,
  MineSkillsView,
} from "./components/MineSkillsView";

const SkillBuildModal = dynamic(
  () => import("../agents/components/agentConfig/SkillBuildModal"),
  { ssr: false }
);
const SkillDetailModal = dynamic(
  () => import("../agents/components/agentConfig/SkillDetailModal"),
  { ssr: false }
);
const MINE_PAGE_SIZE = 6;
const SEARCH_DEBOUNCE_MS = 300;

export function MySkill({ active }: { active: boolean }) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const router = useRouter();
  const params = useParams<{ locale: string }>();
  const locale = params.locale || "en";
  const [minePage, setMinePage] = useState(1);
  const [mineOwnership, setMineOwnership] =
    useState<MineOwnershipFilter>("all");
  const [mineSearch, setMineSearch] = useState("");
  const [mineTagPredicates, setMineTagPredicates] = useState<
    TagResourcePredicate[]
  >([]);
  const [debouncedMineSearch, setDebouncedMineSearch] = useState("");
  const [skillBuildOpen, setSkillBuildOpen] = useState(false);
  const [skillBuildLoaded, setSkillBuildLoaded] = useState(false);
  const [editingSkill, setEditingSkill] = useState<MyEditableSkillItem | null>(
    null
  );
  const [skillDetailLoaded, setSkillDetailLoaded] = useState(false);
  const [viewingSkill, setViewingSkill] = useState<MyEditableSkillItem | null>(
    null
  );
  const { data: tagLibraries } = useTagLibraries();
  const defaultTagLibrary =
    tagLibraries?.find(
      (library) => library.bucket_key === "default_resource"
    ) ?? null;
  const { data: mineTagDefinitions } = useTagDefinitions(
    defaultTagLibrary?.bucket_id ?? null
  );

  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedMineSearch(mineSearch),
      SEARCH_DEBOUNCE_MS
    );
    return () => window.clearTimeout(timer);
  }, [mineSearch]);

  const reviewDeepLink = useMemo(
    () => parseSkillReviewDeepLinkParams(searchParams),
    [searchParams]
  );
  const handleReviewDeepLinkConsumed = useCallback(() => {
    router.replace(`/${locale}/skill-space?tab=mine`);
  }, [locale, router]);
  const mineParams = useMemo(
    () => ({
      ownership: mineOwnership,
      page: minePage,
      page_size: MINE_PAGE_SIZE,
      ...(debouncedMineSearch.trim()
        ? { search: debouncedMineSearch.trim() }
        : {}),
      ...(mineTagPredicates.length > 0
        ? { tag_predicates: mineTagPredicates }
        : {}),
      ...(mineOwnership === "all" &&
      !debouncedMineSearch.trim() &&
      mineTagPredicates.length === 0
        ? { new_skill_padding: true }
        : {}),
    }),
    [debouncedMineSearch, mineOwnership, minePage, mineTagPredicates]
  );
  const {
    data: mineData,
    isLoading: isMineLoading,
    isError: isMineError,
    isFetching: isMineFetching,
    refetch: refetchMine,
  } = useMyEditableSkills(mineParams, active);
  const { data: deepLinkMineData, isLoading: isDeepLinkMineLoading } =
    useMyEditableSkills(
      { ownership: "all", page: 1, page_size: 100, new_skill_padding: false },
      active && reviewDeepLink != null
    );
  const createListingMutation = useCreateSkillRepositoryListing();
  const updateStatusMutation = useUpdateSkillRepositoryStatus();
  const mineItems = mineData?.items ?? [];
  const mineTotal = mineData?.pagination?.total ?? 0;
  const mineCounts = mineData?.counts ?? { all: 0, created: 0, others: 0 };
  const deepLinkFallbackSkill = useMemo(() => {
    if (!reviewDeepLink) return null;
    const items = deepLinkMineData?.items ?? [];
    return (
      items.find(
        (item): item is MyEditableSkillItem =>
          !isNewSkillPaddingItem(item) &&
          item.skill_id === reviewDeepLink.skillId
      ) ?? null
    );
  }, [deepLinkMineData?.items, reviewDeepLink]);

  useEffect(() => {
    if (active) refetchMine().catch(() => {});
  }, [active, refetchMine]);

  useEffect(() => {
    const total = mineData?.pagination?.total;
    if (total == null) return;
    const totalPages = Math.max(1, Math.ceil(total / MINE_PAGE_SIZE));
    if (minePage > totalPages) {
      /* eslint-disable react-hooks/set-state-in-effect -- Clamp after server pagination changes. */
      setMinePage(totalPages);
      /* eslint-enable react-hooks/set-state-in-effect */
    }
  }, [mineData?.pagination?.total, minePage]);

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
        ? t("repository.mine.takeDownSuccess")
        : t("repository.mine.cancelApplySuccess")
    );
  };

  const refreshSkillCaches = async () => {
    await Promise.all([
      invalidateSkillRepositoryCaches(queryClient),
      queryClient.invalidateQueries({ queryKey: [SKILLS_LIST_QUERY_KEY] }),
    ]);
  };

  const handleSkillBuildSuccess = async () => {
    await refreshSkillCaches().catch(() => {});
    setEditingSkill(null);
  };
  return (
    <>
      {active ? (
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
          tagDefinitions={mineTagDefinitions ?? []}
          tagPredicates={mineTagPredicates}
          onTagPredicatesChange={(value) => {
            setMineTagPredicates(value);
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
            setSkillBuildLoaded(true);
            setSkillBuildOpen(true);
          }}
          onEditSkill={(skill) => {
            setEditingSkill(skill);
            setSkillBuildLoaded(true);
            setSkillBuildOpen(true);
          }}
          onViewSkill={(skill) => {
            setSkillDetailLoaded(true);
            setViewingSkill(skill);
          }}
          onDeleteSkill={async (skill) => {
            const name = skill.name?.trim();
            if (!name) {
              message.error(t("skillRepository.delete.emptyName"));
              return;
            }
            const result = await deleteSkillByName(name);
            if (!result.success) {
              message.error(
                result.message || t("repository.mine.deleteFailed")
              );
              throw new Error(result.message || "Delete skill failed");
            }
            message.success(t("repository.mine.deleteSuccess"));
            await refreshSkillCaches();
          }}
          onApplyListing={async (skill, payload) => {
            try {
              await createListingMutation.mutateAsync({
                skillId: skill.skill_id,
                payload,
              });
              message.success(t("repository.mine.applySuccess"));
            } catch (error) {
              if (error instanceof ApiError && Number(error.code) === 403) {
                message.error(t("skillRepository.mine.applyForbidden"));
                return;
              }
              message.error(
                error instanceof Error
                  ? error.message
                  : t("repository.mine.applyError")
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
      ) : null}
      {skillBuildLoaded ? (
        <SkillBuildModal
          isOpen={skillBuildOpen}
          editingSkill={editingSkill}
          onCancel={() => {
            setSkillBuildOpen(false);
            setEditingSkill(null);
          }}
          onSuccess={handleSkillBuildSuccess}
        />
      ) : null}
      {skillDetailLoaded ? (
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
      ) : null}
    </>
  );
}
