"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { App, Grid } from "antd";
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
import { fetchMyEditableSkills } from "@/services/skillRepositoryService";
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
const CARD_GAP = 20;
const MIN_CARD_HEIGHT = 240;
const PAGINATION_HEIGHT = 60;
const SEARCH_DEBOUNCE_MS = 300;

export function MySkill({ active }: { active: boolean }) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const screens = Grid.useBreakpoint();
  const gridRegionRef = useRef<HTMLDivElement>(null);
  const [availableGridHeight, setAvailableGridHeight] = useState<number | null>(
    null
  );
  const columns = screens.xxl
    ? 4
    : screens.xl
      ? 3
      : screens.lg || screens.md || screens.sm
        ? 2
        : screens.xs
          ? 1
          : 4;
  const pageBottomPadding = screens.sm ? 40 : 32;
  const rows = getRowCount(
    Math.max(0, (availableGridHeight ?? 0) - PAGINATION_HEIGHT)
  );
  const pageSize = columns * rows;
  const measureGridHeight = useCallback(() => {
    if (!active || !gridRegionRef.current) return;

    const viewportHeight = window.visualViewport?.height ?? window.innerHeight;
    const { top } = gridRegionRef.current.getBoundingClientRect();
    setAvailableGridHeight(
      Math.max(0, Math.floor(viewportHeight - top - pageBottomPadding - 8))
    );
  }, [active, pageBottomPadding]);

  useEffect(() => {
    if (!active) return;

    const frame = window.requestAnimationFrame(measureGridHeight);
    const observer = new ResizeObserver(measureGridHeight);
    const visualViewport = window.visualViewport;
    if (gridRegionRef.current) observer.observe(gridRegionRef.current);
    window.addEventListener("resize", measureGridHeight);
    visualViewport?.addEventListener("resize", measureGridHeight);

    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", measureGridHeight);
      visualViewport?.removeEventListener("resize", measureGridHeight);
    };
  }, [active, measureGridHeight]);
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
  useEffect(() => {
    if (!active) return;
    const id = Number(searchParams.get("edit_skill_id"));
    if (!Number.isInteger(id) || id <= 0) return;
    let cancelled = false;
    void (async () => {
      try {
        for (let page = 1; ; page += 1) {
          const result = await fetchMyEditableSkills({
            ownership: "all",
            page,
            page_size: 100,
            new_skill_padding: false,
          });
          if (cancelled) return;
          const skill = result.items.find(
            (item): item is MyEditableSkillItem =>
              "skill_id" in item && item.skill_id === id
          );
          if (skill) {
            setEditingSkill(skill);
            setSkillBuildLoaded(true);
            setSkillBuildOpen(true);
            return;
          }
          if (page >= result.pagination.total_pages) {
            message.warning("Skill 不存在或没有编辑权限");
            return;
          }
        }
      } catch {
        if (!cancelled) message.error("Skill 加载失败");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [active, searchParams, message]);
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
      page_size: pageSize,
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
    [debouncedMineSearch, mineOwnership, minePage, mineTagPredicates, pageSize]
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
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    if (minePage > totalPages) {
      /* eslint-disable react-hooks/set-state-in-effect -- Clamp after server pagination changes. */
      setMinePage(totalPages);
      /* eslint-enable react-hooks/set-state-in-effect */
    }
  }, [mineData?.pagination?.total, minePage, pageSize]);
  const gridHeight =
    availableGridHeight === null
      ? undefined
      : Math.max(
          0,
          availableGridHeight - (mineTotal > 0 ? PAGINATION_HEIGHT : 0)
        );

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
          total={mineTotal}
          onPageChange={setMinePage}
          columns={columns}
          rows={rows}
          gridHeight={gridHeight}
          gridRegionRef={gridRegionRef}
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

function getRowCount(availableHeight: number) {
  if (availableHeight <= 0) return 3;
  return Math.min(
    3,
    Math.max(
      1,
      Math.floor((availableHeight + CARD_GAP) / (MIN_CARD_HEIGHT + CARD_GAP))
    )
  );
}
