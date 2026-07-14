"use client";

import { useState } from "react";
import { App, Button, Dropdown, Input } from "antd";
import type { MenuProps } from "antd";
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
  Trash2,
} from "lucide-react";

import { CreateNewSkillCard } from "./CreateNewSkillCard";
import { SkillReviewStatusModal } from "./SkillReviewStatusModal";
import {
  AsyncContent,
  FilterButton,
  PaginationBar,
} from "./SkillRepositoryControls";
import {
  formatRepositoryDate,
  getSkillSourceLabel,
  pickReviewDisplayRepositoryInfo,
} from "./skillRepositoryShared";
import type {
  MyEditableSkillItem,
  MyEditableSkillListItem,
  MySkillRepositoryInfoItem,
  NewSkillPaddingItem,
  SkillRepositoryListingCreatePayload,
  SkillRepositoryListingStatus,
} from "@/types/skillRepository";

function isNewSkillPaddingItem(
  item: MyEditableSkillListItem
): item is NewSkillPaddingItem {
  return "new_skill_padding" in item && item.new_skill_padding === true;
}

export function MineSkillsView({
  skills,
  counts,
  searchQuery,
  onSearchChange,
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
  onDeleteSkill,
  onApplyListing,
  isUpdatingStatus,
  onSetNotShared,
}: {
  skills: MyEditableSkillListItem[];
  counts: { all: number; created: number; others: number };
  searchQuery: string;
  onSearchChange: (value: string) => void;
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
  onDeleteSkill: (skill: MyEditableSkillItem) => Promise<void>;
  onApplyListing: (
    skill: MyEditableSkillItem,
    payload: SkillRepositoryListingCreatePayload
  ) => Promise<void>;
  isUpdatingStatus: boolean;
  onSetNotShared: (repositoryInfo: MySkillRepositoryInfoItem) => Promise<void>;
}) {
  const { message, modal } = App.useApp();
  const [reviewModalOpen, setReviewModalOpen] = useState(false);
  const [reviewModalSkill, setReviewModalSkill] =
    useState<MyEditableSkillItem | null>(null);
  const [reviewModalInfo, setReviewModalInfo] =
    useState<MySkillRepositoryInfoItem | null>(null);

  const openReviewModal = (skill: MyEditableSkillItem) => {
    const repositoryInfo = pickReviewDisplayRepositoryInfo(
      skill.repository_info ?? []
    );
    if (!repositoryInfo) return;
    setReviewModalSkill(skill);
    setReviewModalInfo(repositoryInfo);
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
      message.error(error instanceof Error ? error.message : "状态更新失败");
      throw error;
    }
  };

  const handleEnableSkill = (skill: MyEditableSkillItem) => {
    const title = skill.name?.trim() || "未命名 Skill";
    modal.confirm({
      title: `确认上架 ${title}？`,
      content: "上架后将提交管理员审批，审批通过后会出现在 Skill 仓库。",
      centered: true,
      okText: "提交审批",
      cancelText: "取消",
      onOk: async () => {
        await onApplyListing(skill, {
          icon: "skill",
          tags: skill.tags ?? [],
        });
      },
    });
  };

  const handleDeleteSkill = (skill: MyEditableSkillItem) => {
    const title = skill.name?.trim() || "未命名 Skill";
    modal.confirm({
      title: "删除 Skill",
      content: `确认删除 ${title}？`,
      okText: "删除",
      cancelText: "取消",
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
            placeholder="搜索Skill名称、描述或标签"
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
          创建 Skill
        </Button>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <FilterButton active onClick={() => {}}>
          全部
          <span className="ml-1 text-xs opacity-80">{counts.all}</span>
        </FilterButton>
      </div>

      <p className="text-sm text-slate-500 dark:text-slate-400">
        共 {counts.all} 个服务 · 标题旁带 Hub 标签的已上架到仓库
      </p>

      <AsyncContent
        isLoading={isLoading}
        isError={isError}
        isFetching={isFetching}
        onRetry={onRetry}
        isEmpty={false}
        emptyDescription="暂无可管理 Skill"
      >
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
                onDelete={() => handleDeleteSkill(skill)}
                onApplyListing={() => handleEnableSkill(skill)}
                onViewReview={() => openReviewModal(skill)}
              />
            )
          )}
        </div>
      </AsyncContent>

      <PaginationBar
        page={page}
        pageSize={pageSize}
        total={total}
        onPageChange={onPageChange}
      />

      <SkillReviewStatusModal
        open={reviewModalOpen}
        skill={reviewModalSkill}
        repositoryInfo={reviewModalInfo}
        isUpdatingStatus={isUpdatingStatus}
        onClose={closeReviewModal}
        onSetNotShared={handleSetNotShared}
      />
    </div>
  );
}

const MINE_SKILL_STATUS_LABELS: Record<SkillRepositoryListingStatus, string> = {
  not_shared: "未上架",
  pending_review: "审批中",
  rejected: "已驳回",
  shared: "已上架",
};

const MINE_SKILL_STATUS_CLASS: Record<SkillRepositoryListingStatus, string> = {
  not_shared:
    "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  pending_review:
    "bg-orange-50 text-orange-700 dark:bg-orange-500/10 dark:text-orange-300",
  rejected: "bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300",
  shared:
    "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
};

function MineSkillCard({
  skill,
  onEdit,
  onDelete,
  onApplyListing,
  onViewReview,
}: {
  skill: MyEditableSkillItem;
  onEdit: () => void;
  onDelete: () => void;
  onApplyListing: () => void;
  onViewReview: () => void;
}) {
  const latestRepository = pickReviewDisplayRepositoryInfo(
    skill.repository_info ?? []
  );
  const repositoryStatus = latestRepository?.status ?? "not_shared";
  const hasRepositoryInfo = (skill.repository_info ?? []).length > 0;
  const canApplyListing =
    !latestRepository || latestRepository.status === "rejected";
  const isEnabled = latestRepository?.status === "shared";
  const canEdit = skill.permission !== "READ_ONLY";
  const updatedAt = formatRepositoryDate(skill.updated_at ?? skill.update_time);
  const sourceLabel = getSkillSourceLabel(skill.source);
  const tags = skill.tags?.filter((tag) => tag.trim()) ?? [];
  const isPendingReview = repositoryStatus === "pending_review";
  const menuItems: MenuProps["items"] = [
    ...(isPendingReview
      ? [
          {
            key: "review",
            label: "查看审批进度",
            icon: <ClipboardCheck className="size-3.5" aria-hidden />,
            onClick: onViewReview,
          },
        ]
      : []),
    {
      key: "delete",
      label: "删除",
      icon: <Trash2 className="size-3.5" aria-hidden />,
      danger: true,
      onClick: onDelete,
    },
  ];

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
                {skill.name || "未命名 Skill"}
              </h3>
              {hasRepositoryInfo ? (
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
                {MINE_SKILL_STATUS_LABELS[repositoryStatus]}
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
              aria-label="更多操作"
            />
          </Dropdown>
        ) : null}
      </div>

      <p className="mt-3 line-clamp-2 min-h-[2.75rem] text-sm leading-relaxed text-slate-600 dark:text-slate-300">
        {skill.description || "暂无描述"}
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
              编辑
            </Button>
          ) : (
            <Button
              type="default"
              className="min-w-0 flex-1"
              icon={<Eye className="size-3.5" aria-hidden />}
              disabled
            >
              查看
            </Button>
          )}
          <Button
            type={isEnabled ? "default" : "primary"}
            className="min-w-0 flex-1"
            icon={<Power className="size-3.5" aria-hidden />}
            disabled={
              !canEdit || isEnabled || repositoryStatus === "pending_review"
            }
            onClick={canApplyListing ? onApplyListing : onViewReview}
          >
            {isEnabled ? "已上架" : "上架"}
          </Button>
        </div>
      </div>
    </article>
  );
}
