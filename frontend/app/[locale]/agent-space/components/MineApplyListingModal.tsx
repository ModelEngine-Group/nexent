"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { App, Button, Dropdown, Input, Modal, Select, Spin } from "antd";
import { ChevronDown, Share2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  AGENT_REPOSITORY_ICONS,
  AGENT_REPOSITORY_PRESET_TAGS,
} from "@/const/agentRepository";
import { useAgentRepositoryListings } from "@/hooks/agentRepository/useAgentRepositoryListings";
import { getAgentRepositoryTagLabel, resolveAgentRepositoryTagForSubmit } from "@/lib/agentRepositoryLabels";
import { isSingleSimpleEmoji } from "@/lib/agentRepositoryIcon";
import {
  buildApplyListingFormPrefill,
  pickApplyListingPrefillSource,
} from "@/lib/agentRepositoryMine";
import type {
  AgentRepositoryListingCreatePayload,
  MyEditableAgentItem,
} from "@/types/agentRepository";

const MAX_TAGS = 5;
const MAX_TAG_LENGTH = 20;
const MAX_ICON_LENGTH = 32;

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

  const icons = AGENT_REPOSITORY_ICONS;
  const presetTags = AGENT_REPOSITORY_PRESET_TAGS;

  const [selectedIcon, setSelectedIcon] = useState<string | null>(null);
  const [iconInput, setIconInput] = useState("");
  const [iconError, setIconError] = useState<string | null>(null);
  const [presetDropdownOpen, setPresetDropdownOpen] = useState(false);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [listingContent, setListingContent] = useState("");

  const agentId = agent?.agent_id;
  const {
    data: listingsData,
    isSuccess: isListingsSuccess,
    isFetching: isListingsFetching,
  } = useAgentRepositoryListings(
    agentId != null
      ? { agent_id: agentId, page: 1, page_size: 100 }
      : undefined,
    open && agentId != null
  );

  const tagOptions = useMemo(
    () =>
      presetTags.map((tag) => ({
        label: getAgentRepositoryTagLabel(tag, t),
        value: tag,
      })),
    [presetTags, t]
  );

  const invalidIconMessage = t(
    "agentRepository.mine.applyModal.validation.iconInvalid"
  );

  const applyIconInputFromValue = useCallback(
    (value: string, showErrorWhenInvalid = true) => {
      setIconInput(value);

      const trimmedValue = value.trim();
      if (!trimmedValue) {
        setSelectedIcon(null);
        setIconError(null);
        return;
      }

      if (isSingleSimpleEmoji(trimmedValue)) {
        setSelectedIcon(trimmedValue);
        setIconError(null);
        return;
      }

      setSelectedIcon(null);
      setIconError(showErrorWhenInvalid ? invalidIconMessage : null);
    },
    [invalidIconMessage]
  );

  const clearIconState = useCallback(() => {
    setIconInput("");
    setSelectedIcon(null);
    setIconError(null);
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }

    if (!agent || !isListingsSuccess) {
      clearIconState();
      setSelectedTags([]);
      setListingContent("");
      return;
    }

    const source = pickApplyListingPrefillSource(
      listingsData?.items ?? [],
      agent.version_label
    );
    const prefill = buildApplyListingFormPrefill(source, {
      maxTags: MAX_TAGS,
    });

    if (!prefill) {
      clearIconState();
      setSelectedTags([]);
      setListingContent("");
      return;
    }

    const trimmedIcon = prefill.icon?.trim();
    if (trimmedIcon && isSingleSimpleEmoji(trimmedIcon)) {
      applyIconInputFromValue(trimmedIcon, false);
    } else {
      clearIconState();
    }

    setSelectedTags(prefill.tags);
    setListingContent("");
  }, [
    open,
    agent,
    isListingsSuccess,
    listingsData,
    clearIconState,
    applyIconInputFromValue,
  ]);

  const title =
    agent?.name?.trim() || t("agentRepository.card.untitled");

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

  const handlePresetIconClick = (icon: string) => {
    applyIconInputFromValue(icon, false);
    setPresetDropdownOpen(false);
  };

  const presetDropdown = (
    <div className="min-w-[280px] rounded-lg border border-slate-200 bg-white p-3 shadow-lg dark:border-slate-700 dark:bg-slate-900">
      <div className="grid grid-cols-5 gap-2">
        {icons.map((icon) => (
          <button
            key={icon}
            type="button"
            onClick={() => handlePresetIconClick(icon)}
            className="flex size-10 items-center justify-center rounded-lg border border-slate-200 text-2xl transition-colors hover:border-primary hover:bg-primary/5 dark:border-slate-700 dark:hover:border-primary"
            aria-label={icon}
          >
            <span aria-hidden>{icon}</span>
          </button>
        ))}
      </div>
    </div>
  );

  const handleSubmit = () => {
    if (iconInput.trim() && !isSingleSimpleEmoji(iconInput)) {
      setIconError(invalidIconMessage);
      message.warning(invalidIconMessage);
      return;
    }

    if (!selectedIcon) {
      message.warning(t("agentRepository.mine.applyModal.validation.icon"));
      return;
    }

    const tags = normalizeTags(selectedTags).map((tag) =>
      resolveAgentRepositoryTagForSubmit(tag, t)
    );
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
      tags,
      content: listingContent.trim(),
    });
  };

  return (
    <Modal
      open={open && agent != null}
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
          <Button type="primary" loading={isSubmitting} onClick={handleSubmit}>
            {t("agentRepository.mine.applyModal.submit")}
          </Button>
        </div>
      }
    >
      <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
        {t("agentRepository.mine.applyModal.agentName", { name: title })}
      </p>

      <Spin spinning={isListingsFetching && open}>
        <div className="space-y-5">
          <section className="space-y-2">
            <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
              {t("agentRepository.mine.applyModal.icon")}
            </p>
            <Input
              value={iconInput}
              onChange={(event) =>
                applyIconInputFromValue(event.target.value)
              }
              maxLength={MAX_ICON_LENGTH}
              status={iconError ? "error" : undefined}
              className="w-[5.25rem] shrink-0 text-2xl"
              styles={{
                input: {
                  paddingInline: 2,
                  textAlign: "center",
                },
              }}
              suffix={
                <Dropdown
                  open={presetDropdownOpen}
                  onOpenChange={setPresetDropdownOpen}
                  trigger={["click"]}
                  popupRender={() => presetDropdown}
                >
                  <button
                    type="button"
                    className="inline-flex items-center text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                    aria-label={t(
                      "agentRepository.mine.applyModal.iconPresetPicker"
                    )}
                    onClick={(event) => event.stopPropagation()}
                  >
                    <ChevronDown className="size-4" aria-hidden />
                  </button>
                </Dropdown>
              }
            />
            {iconError ? (
              <p className="text-xs text-red-500">{iconError}</p>
            ) : (
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t("agentRepository.mine.applyModal.customIconHint")}
              </p>
            )}
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

          <section className="space-y-2">
            <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
              {t("agentRepository.mine.applyModal.content")}
            </p>
            <Input.TextArea
              value={listingContent}
              onChange={(event) => setListingContent(event.target.value)}
              rows={4}
              placeholder={t(
                "agentRepository.mine.applyModal.contentPlaceholder"
              )}
            />
          </section>
        </div>
      </Spin>
    </Modal>
  );
}
