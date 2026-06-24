"use client";

import { useEffect, useMemo, useState } from "react";
import { App, Button, Modal, Select, Spin } from "antd";
import { Share2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAgentRepositoryOptions } from "@/hooks/agentRepository/useAgentRepositoryListings";
import type {
  AgentRepositoryListingCreatePayload,
  MyEditableAgentItem,
} from "@/types/agentRepository";

const MAX_TAGS = 5;
const MAX_TAG_LENGTH = 20;

interface MineApplyListingModalProps {
  open: boolean;
  agent: MyEditableAgentItem | null;
  isSubmitting?: boolean;
  onClose: () => void;
  onSubmit: (payload: AgentRepositoryListingCreatePayload) => void;
}

export function MineApplyListingModal({
  open,
  agent,
  isSubmitting = false,
  onClose,
  onSubmit,
}: MineApplyListingModalProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  const { data: icons = [], isLoading: isIconsLoading } =
    useAgentRepositoryOptions("icons", open);
  const { data: categories = [], isLoading: isCategoriesLoading } =
    useAgentRepositoryOptions("categories", open);
  const { data: presetTags = [], isLoading: isTagsLoading } =
    useAgentRepositoryOptions("tags", open);

  const [selectedIcon, setSelectedIcon] = useState<string | null>(null);
  const [selectedCategoryId, setSelectedCategoryId] = useState<number | null>(
    null
  );
  const [selectedTags, setSelectedTags] = useState<string[]>([]);

  const isOptionsLoading =
    isIconsLoading || isCategoriesLoading || isTagsLoading;

  const tagOptions = useMemo(
    () =>
      presetTags.map((tag) => ({
        label: tag,
        value: tag,
      })),
    [presetTags]
  );

  useEffect(() => {
    if (!open) {
      return;
    }
    setSelectedIcon(icons[0] ?? null);
    setSelectedCategoryId(categories[0]?.id ?? null);
    setSelectedTags([]);
  }, [open, icons, categories]);

  if (!agent) {
    return null;
  }

  const title = agent.name?.trim() || t("agentRepository.card.untitled");

  const normalizeTags = (tags: string[]) => {
    const normalized: string[] = [];
    const seen = new Set<string>();
    for (const rawTag of tags) {
      const tag = rawTag.trim();
      if (!tag || seen.has(tag)) {
        continue;
      }
      seen.add(tag);
      normalized.push(tag);
    }
    return normalized;
  };

  const handleSubmit = () => {
    if (!selectedIcon) {
      message.warning(t("agentRepository.mine.applyModal.validation.icon"));
      return;
    }
    if (selectedCategoryId == null) {
      message.warning(t("agentRepository.mine.applyModal.validation.category"));
      return;
    }

    const tags = normalizeTags(selectedTags);
    if (tags.length === 0) {
      message.warning(t("agentRepository.mine.applyModal.validation.tags"));
      return;
    }
    if (tags.length > MAX_TAGS) {
      message.warning(
        t("agentRepository.mine.applyModal.validation.tagsMax", {
          count: MAX_TAGS,
        })
      );
      return;
    }
    if (tags.some((tag) => tag.length > MAX_TAG_LENGTH)) {
      message.warning(
        t("agentRepository.mine.applyModal.validation.tagLength", {
          count: MAX_TAG_LENGTH,
        })
      );
      return;
    }

    onSubmit({
      icon: selectedIcon,
      category_id: selectedCategoryId,
      tags,
    });
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      centered
      destroyOnHidden
      title={
        <span className="inline-flex items-center gap-2">
          <Share2 className="size-5 text-primary" aria-hidden />
          {t("agentRepository.mine.applyModal.title")}
        </span>
      }
      footer={
        <div className="flex flex-wrap justify-end gap-2">
          <Button onClick={onClose} disabled={isSubmitting}>
            {t("common.cancel")}
          </Button>
          <Button
            type="primary"
            loading={isSubmitting}
            onClick={handleSubmit}
            disabled={isOptionsLoading}
          >
            {t("agentRepository.mine.applyModal.submit")}
          </Button>
        </div>
      }
    >
      <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
        {t("agentRepository.mine.applyModal.agentName", { name: title })}
      </p>

      {isOptionsLoading ? (
        <div className="flex items-center justify-center py-10">
          <Spin />
        </div>
      ) : (
        <div className="space-y-5">
          <section className="space-y-2">
            <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
              {t("agentRepository.mine.applyModal.icon")}
            </p>
            <div className="flex flex-wrap gap-2">
              {icons.map((icon) => {
                const isSelected = selectedIcon === icon;
                return (
                  <button
                    key={icon}
                    type="button"
                    onClick={() => setSelectedIcon(icon)}
                    className={`flex size-11 items-center justify-center rounded-xl border text-2xl transition-colors ${
                      isSelected
                        ? "border-primary bg-primary/10 ring-2 ring-primary/30"
                        : "border-slate-200 bg-slate-50 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-800"
                    }`}
                    aria-label={icon}
                    aria-pressed={isSelected}
                  >
                    <span aria-hidden>{icon}</span>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="space-y-2">
            <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
              {t("agentRepository.mine.applyModal.category")}
            </p>
            <Select
              className="w-full"
              value={selectedCategoryId ?? undefined}
              onChange={setSelectedCategoryId}
              options={categories.map((category) => ({
                label: category.name,
                value: category.id,
              }))}
              placeholder={t("agentRepository.mine.applyModal.categoryPlaceholder")}
            />
          </section>

          <section className="space-y-2">
            <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
              {t("agentRepository.mine.applyModal.tags")}
            </p>
            <Select
              mode="tags"
              className="w-full"
              value={selectedTags}
              onChange={setSelectedTags}
              options={tagOptions}
              maxCount={MAX_TAGS}
              placeholder={t("agentRepository.mine.applyModal.tagsPlaceholder")}
            />
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {t("agentRepository.mine.applyModal.tagsHint", {
                count: MAX_TAGS,
              })}
            </p>
          </section>
        </div>
      )}
    </Modal>
  );
}
