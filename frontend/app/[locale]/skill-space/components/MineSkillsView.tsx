"use client";

import { useEffect, useRef, useState } from "react";
import { App, Button, Dropdown, Input, Popover, Tooltip } from "antd";
import type { MenuProps } from "antd";
import { useTranslation } from "react-i18next";
import {
  Bot,
  ClipboardCheck,
  Clock,
  Eye,
  MoreHorizontal,
  Pencil,
  Plus,
  Power,
  Search,
  Share2,
  Tag,
  Trash2,
} from "lucide-react";

import { CreateNewSkillCard } from "./CreateNewSkillCard";
import { MineApplyListingModal } from "./MineApplyListingModal";
import { SkillReviewStatusModal } from "./SkillReviewStatusModal";
import {
  AsyncContent,
  FilterButton,
  PaginationBar,
} from "./SkillRepositoryControls";
import {
  formatRepositoryDate,
  getSkillRepositoryStatusLabel,
  getSkillSourceLabel,
  pickReviewDisplayRepositoryInfo,
} from "./skillRepositoryShared";
import type {
  MyEditableSkillItem,
  MyEditableSkillListItem,
  MySkillRepositoryInfoItem,
  MineOwnershipFilter,
  NewSkillPaddingItem,
  SkillRepositoryListingCreatePayload,
  SkillRepositoryListingStatus,
} from "@/types/skillRepository";
import TagFilterControls from "@/components/tag/TagFilterControls";
import type { TagDefinition, TagResourcePredicate } from "@/types/tagManagement";

const MINE_OWNERSHIP_FILTERS: MineOwnershipFilter[] = [
  "all",
  "created",
  "others",
];

export function isNewSkillPaddingItem(
  item: MyEditableSkillListItem
): item is NewSkillPaddingItem {
  return "new_skill_padding" in item && item.new_skill_padding === true;
}

export type SkillReviewDeepLinkTarget = {
  skillRepositoryId: number;
  skillId: number;
};

function findRepositoryInfoById(
  repositoryInfo: MySkillRepositoryInfoItem[],
  skillRepositoryId: number
): MySkillRepositoryInfoItem | null {
  return (
    repositoryInfo.find(
      (item) => item.skill_repository_id === skillRepositoryId
    ) ?? null
  );
}

export function MineSkillsView({
  skills,
  counts,
  ownership,
  onOwnershipChange,
  searchQuery,
  onSearchChange,
  tagDefinitions,
  tagPredicates,
  onTagPredicatesChange,
  isLoading,
  isError,
  isFetching,
  page,
  pageSize,
  total,
  onPageChange,
  onRetry,
  onCreateSkill,
  onEditSkill,
  onViewSkill,
  onDeleteSkill,
  onApplyListing,
  isUpdatingStatus,
  onSetNotShared,
  reviewDeepLink = null,
  deepLinkFallbackSkill = null,
  deepLinkFallbackLoading = false,
  onReviewDeepLinkConsumed,
}: {
  skills: MyEditableSkillListItem[];
  counts: { all: number; created: number; others: number };
  ownership: MineOwnershipFilter;
  onOwnershipChange: (ownership: MineOwnershipFilter) => void;
  searchQuery: string;
  onSearchChange: (value: string) => void;
  tagDefinitions: TagDefinition[];
  tagPredicates: TagResourcePredicate[];
  onTagPredicatesChange: (predicates: TagResourcePredicate[]) => void;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onRetry: () => void;
  onCreateSkill: () => void;
  onEditSkill: (skill: MyEditableSkillItem) => void;
  onViewSkill: (skill: MyEditableSkillItem) => void;
  onDeleteSkill: (skill: MyEditableSkillItem) => Promise<void>;
  onApplyListing: (
    skill: MyEditableSkillItem,
    payload: SkillRepositoryListingCreatePayload
  ) => Promise<void>;
  isUpdatingStatus: boolean;
  onSetNotShared: (repositoryInfo: MySkillRepositoryInfoItem) => Promise<void>;
  reviewDeepLink?: SkillReviewDeepLinkTarget | null;
  deepLinkFallbackSkill?: MyEditableSkillItem | null;
  deepLinkFallbackLoading?: boolean;
  onReviewDeepLinkConsumed?: () => void;
}) {
  const { t } = useTranslation("common");
  const { message, modal } = App.useApp();
  const [reviewModalOpen, setReviewModalOpen] = useState(false);
  const [reviewModalSkill, setReviewModalSkill] =
    useState<MyEditableSkillItem | null>(null);
  const [reviewModalInfo, setReviewModalInfo] =
    useState<MySkillRepositoryInfoItem | null>(null);
  const [applyModalOpen, setApplyModalOpen] = useState(false);
  const [applyModalSkill, setApplyModalSkill] =
    useState<MyEditableSkillItem | null>(null);
  const [applySubmitting, setApplySubmitting] = useState(false);
  const consumedDeepLinkRef = useRef<number | null>(null);
  const ownershipLabelKey: Record<MineOwnershipFilter, string> = {
    all: "repository.mine.filter.all",
    created: "repository.mine.filter.created",
    others: "repository.mine.filter.others",
  };

  const openReviewModal = (
    skill: MyEditableSkillItem,
    repositoryInfo?: MySkillRepositoryInfoItem | null
  ) => {
    const info =
      repositoryInfo ??
      pickReviewDisplayRepositoryInfo(skill.repository_info ?? []);
    if (!info) {
      return;
    }
    setReviewModalSkill(skill);
    setReviewModalInfo(info);
    setReviewModalOpen(true);
  };

  const closeReviewModal = () => {
    setReviewModalOpen(false);
    setReviewModalSkill(null);
    setReviewModalInfo(null);
  };

  const handleSetNotShared = async () => {
    if (!reviewModalInfo) return;

    try {
      await onSetNotShared(reviewModalInfo);
      closeReviewModal();
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("skillRepository.common.statusUpdateFailed")
      );
      throw error;
    }
  };

  useEffect(() => {
    if (!reviewDeepLink) {
      consumedDeepLinkRef.current = null;
      return;
    }

    if (consumedDeepLinkRef.current === reviewDeepLink.skillRepositoryId) {
      return;
    }

    if (isLoading && deepLinkFallbackLoading) {
      return;
    }

    const skillFromList = skills.find(
      (item): item is MyEditableSkillItem =>
        !isNewSkillPaddingItem(item) && item.skill_id === reviewDeepLink.skillId
    );
    const skill = skillFromList ?? deepLinkFallbackSkill;

    if (!skill) {
      if (isLoading || deepLinkFallbackLoading) {
        return;
      }
      message.error(t("notifications.deepLink.skillNotFound"));
      consumedDeepLinkRef.current = reviewDeepLink.skillRepositoryId;
      onReviewDeepLinkConsumed?.();
      return;
    }

    const repositoryInfo = findRepositoryInfoById(
      skill.repository_info ?? [],
      reviewDeepLink.skillRepositoryId
    );

    if (!repositoryInfo) {
      message.error(t("notifications.deepLink.skillNotFound"));
      consumedDeepLinkRef.current = reviewDeepLink.skillRepositoryId;
      onReviewDeepLinkConsumed?.();
      return;
    }

    openReviewModal(skill, repositoryInfo);
    consumedDeepLinkRef.current = reviewDeepLink.skillRepositoryId;
    onReviewDeepLinkConsumed?.();
  }, [
    deepLinkFallbackLoading,
    deepLinkFallbackSkill,
    isLoading,
    message,
    onReviewDeepLinkConsumed,
    reviewDeepLink,
    skills,
    t,
  ]);

  const handleEnableSkill = (skill: MyEditableSkillItem) => {
    setApplyModalSkill(skill);
    setApplyModalOpen(true);
  };

  const handleConfirmApply = async (
    payload: SkillRepositoryListingCreatePayload
  ) => {
    if (!applyModalSkill) {
      return;
    }
    setApplySubmitting(true);
    try {
      await onApplyListing(applyModalSkill, payload);
    } finally {
      setApplySubmitting(false);
    }
  };

  const handleDeleteSkill = (skill: MyEditableSkillItem) => {
    const title = skill.name?.trim() || t("skillRepository.common.untitled");
    modal.confirm({
      title: t("skillRepository.mine.deleteTitle"),
      content: t("skillRepository.mine.deleteContent", { name: title }),
      okText: t("common.delete"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: async () => {
        await onDeleteSkill(skill);
      },
    });
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
        <div className="relative w-full sm:flex-1">
          <Input
            value={searchQuery}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={t("skillRepository.searchPlaceholder")}
            prefix={<Search className="size-4 text-slate-400" aria-hidden />}
            className="h-11 rounded-xl"
            allowClear
          />
        </div>
        <Button
          type="primary"
          className="flex h-11 shrink-0 items-center gap-1.5"
          icon={<Plus className="size-4" />}
          onClick={onCreateSkill}
        >
          {t("skillRepository.mine.createSkill")}
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <div className="flex flex-wrap gap-1.5">
          {MINE_OWNERSHIP_FILTERS.map((filter) => (
            <FilterButton
              key={filter}
              active={ownership === filter}
              onClick={() => onOwnershipChange(filter)}
            >
              {t(ownershipLabelKey[filter])}
              <span className="ml-1 text-xs opacity-80">{counts[filter]}</span>
            </FilterButton>
          ))}
        </div>
        <div className="ml-auto shrink-0">
          <Popover
            trigger="click"
            placement="bottomRight"
            content={
              <div className="w-72">
                <TagFilterControls
                  definitions={tagDefinitions}
                  value={tagPredicates}
                  onChange={onTagPredicatesChange}
                />
                {tagPredicates.length > 0 ? (
                  <button
                    type="button"
                    className="mt-2 text-xs text-blue-600 hover:underline"
                    onClick={() => onTagPredicatesChange([])}
                  >
                    {t("repository.tagFilter.clear")}
                  </button>
                ) : null}
              </div>
            }
          >
            <Button
              type={tagPredicates.length > 0 ? "primary" : "default"}
              className="h-11"
              icon={<Tag className="size-3.5" aria-hidden />}
            >
              {t("repository.tagFilter.button")}
            </Button>
          </Popover>
        </div>
      </div>

      <p className="text-sm text-slate-500 dark:text-slate-400">
        {t("skillRepository.mine.summary", { count: counts.all })}
      </p>

      <AsyncContent
        isLoading={isLoading}
        isError={isError}
        isFetching={isFetching}
        onRetry={onRetry}
        isEmpty={skills.length === 0}
        emptyDescription={t("skillRepository.mine.empty")}
      >
        <>
          <div className="grid items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {skills.map((skill) =>
              isNewSkillPaddingItem(skill) ? (
                <div key="new-skill-padding" className="h-full">
                  <CreateNewSkillCard onClick={onCreateSkill} />
                </div>
              ) : (
                <MineSkillCard
                  key={skill.skill_id}
                  skill={skill}
                  onEdit={() => onEditSkill(skill)}
                  onView={() => onViewSkill(skill)}
                  onDelete={() => handleDeleteSkill(skill)}
                  onApplyListing={() => handleEnableSkill(skill)}
                  onViewReview={() => openReviewModal(skill)}
                />
              )
            )}
          </div>
          <PaginationBar
            page={page}
            pageSize={pageSize}
            total={total}
            onPageChange={onPageChange}
          />
        </>
      </AsyncContent>

      <SkillReviewStatusModal
        open={reviewModalOpen}
        skill={reviewModalSkill}
        repositoryInfo={reviewModalInfo}
        isUpdatingStatus={isUpdatingStatus}
        onClose={closeReviewModal}
        onSetNotShared={handleSetNotShared}
      />
      <MineApplyListingModal
        open={applyModalOpen}
        skill={applyModalSkill}
        loading={applySubmitting}
        onClose={() => {
          setApplyModalOpen(false);
          setApplyModalSkill(null);
        }}
        onConfirm={handleConfirmApply}
      />
    </div>
  );
}

const MINE_SKILL_STATUS_CLASS: Record<SkillRepositoryListingStatus, string> = {
  not_shared:
    "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  pending_review:
    "bg-orange-50 text-orange-700 dark:bg-orange-500/10 dark:text-orange-300",
  rejected: "bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300",
  shared:
    "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
};

function getApplyButtonLabel(
  hasRepositoryInfo: boolean,
  repositoryStatus: SkillRepositoryListingStatus,
  t: (key: string) => string
) {
  if (hasRepositoryInfo) {
    return getSkillRepositoryStatusLabel(t, repositoryStatus);
  }
  return t("skillRepository.mine.button.apply");
}

function getMineSkillMenuItems({
  canPublish,
  hasRepositoryInfo,
  t,
  onViewReview,
  onDelete,
}: {
  canPublish: boolean;
  hasRepositoryInfo: boolean;
  t: (key: string) => string;
  onViewReview: () => void;
  onDelete: () => void;
}): MenuProps["items"] {
  const items: MenuProps["items"] = [];
  if (canPublish && hasRepositoryInfo) {
    items.push({
      key: "review",
      label: t("skillRepository.mine.viewReviewProgress"),
      icon: <ClipboardCheck className="size-3.5" aria-hidden />,
      onClick: onViewReview,
    });
  }
  items.push({
    key: "delete",
    label: t("common.delete"),
    icon: <Trash2 className="size-3.5" aria-hidden />,
    danger: true,
    onClick: onDelete,
  });
  return items;
}

function MineSkillCard({
  skill,
  onEdit,
  onView,
  onDelete,
  onApplyListing,
  onViewReview,
}: {
  skill: MyEditableSkillItem;
  onEdit: () => void;
  onView: () => void;
  onDelete: () => void;
  onApplyListing: () => void;
  onViewReview: () => void;
}) {
  const { t } = useTranslation("common");
  const latestRepository = pickReviewDisplayRepositoryInfo(
    skill.repository_info ?? []
  );
  const repositoryInfo = skill.repository_info ?? [];
  const hasRepositoryInfo = latestRepository != null;
  const repositoryStatus = latestRepository?.status ?? "not_shared";
  const hasSharedRepository = repositoryInfo.some(
    (info) => info.status === "shared"
  );
  const canEdit =
    skill.permission !== "READ_ONLY" && skill.permission !== "PRIVATE";
  const canPublish = skill.can_publish === true;
  const updatedAt = formatRepositoryDate(skill.updated_at ?? skill.update_time);
  const sourceLabel = getSkillSourceLabel(skill.source, t);
  const tags = skill.tags?.filter((tag) => tag.trim()) ?? [];
  const canApplyListing = canPublish && !hasRepositoryInfo;
  const applyButtonLabel = getApplyButtonLabel(
    hasRepositoryInfo,
    repositoryStatus,
    t
  );
  const menuItems = getMineSkillMenuItems({
    canPublish,
    hasRepositoryInfo,
    t,
    onViewReview,
    onDelete,
  });

  return (
    <article className="flex min-h-[200px] flex-col rounded-xl border border-border bg-background p-4 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Bot className="size-5" aria-hidden />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              <h3 className="truncate text-base font-semibold text-slate-900 dark:text-slate-100">
                {skill.name || t("skillRepository.common.untitled")}
              </h3>
              {hasSharedRepository ? (
                <span className="inline-flex items-center gap-0.5 rounded-md bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">
                  <Share2 className="size-2.5" aria-hidden />
                  Hub
                </span>
              ) : null}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <span
                className={`rounded-md px-1.5 py-0.5 text-[11px] font-medium ${MINE_SKILL_STATUS_CLASS[repositoryStatus]}`}
              >
                {getSkillRepositoryStatusLabel(t, repositoryStatus)}
              </span>
            </div>
          </div>
        </div>
        {canEdit ? (
          <Dropdown menu={{ items: menuItems }} trigger={["click"]}>
            <Button
              type="text"
              size="small"
              className="size-8 shrink-0 text-slate-400 hover:text-slate-600"
              icon={<MoreHorizontal className="size-4" aria-hidden />}
              aria-label={t("skillRepository.common.moreActions")}
            />
          </Dropdown>
        ) : null}
      </div>

      <p className="mt-3 line-clamp-2 min-h-[2.75rem] text-sm leading-relaxed text-slate-600 dark:text-slate-300">
        {skill.description || t("skillRepository.common.noDescription")}
      </p>

      {tags.length > 0 ? (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {tags.map((tag) => (
            <span
              key={tag}
              className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200"
            >
              {tag}
            </span>
          ))}
        </div>
      ) : null}

      <div className="mt-auto flex flex-col gap-3 pt-3">
        <div className="flex min-h-[1.75rem] items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
          {updatedAt ? (
            <span className="inline-flex min-w-0 items-center gap-1 truncate">
              <Clock className="size-3.5" aria-hidden />
              {updatedAt}
            </span>
          ) : (
            <span />
          )}
          <span className="inline-flex shrink-0 items-center gap-1.5">
            <span
              className="size-1.5 shrink-0 rounded-full bg-primary"
              aria-hidden
            />
            {sourceLabel}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {canEdit ? (
            <Button
              type="default"
              className="min-w-0 flex-1"
              icon={<Pencil className="size-3.5" aria-hidden />}
              onClick={onEdit}
            >
              {t("common.edit")}
            </Button>
          ) : (
            <Button
              type="default"
              className="min-w-0 flex-1"
              icon={<Eye className="size-3.5" aria-hidden />}
              onClick={onView}
            >
              {t("skillRepository.common.view")}
            </Button>
          )}
          <Tooltip
            title={
              canPublish ? undefined : t("skillRepository.mine.applyForbidden")
            }
          >
            <span className="min-w-0 flex-1">
              <Button
                type={hasSharedRepository ? "default" : "primary"}
                className="w-full"
                icon={<Power className="size-3.5" aria-hidden />}
                disabled={!canPublish}
                onClick={canApplyListing ? onApplyListing : onViewReview}
              >
                {applyButtonLabel}
              </Button>
            </span>
          </Tooltip>
        </div>
      </div>
    </article>
  );
}
