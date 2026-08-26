"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { App, Button, Dropdown, Input, Modal, Select, Spin } from "antd";
import { ChevronDown, Share2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { AGENT_REPOSITORY_ICONS } from "@/const/agentRepository";
import { useAgentRepositoryListings } from "@/hooks/agentRepository/useAgentRepositoryListings";
import {
  getAgentRepositoryTagLabel,
  resolveAgentRepositoryTagForSubmit,
} from "@/lib/agentRepositoryLabels";
import { isSingleSimpleEmoji } from "@/lib/agentRepositoryIcon";
import {
  useTagAssignments,
  useTagDefinitions,
  useTagLibraries,
} from "@/hooks/useTagManagement";
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
  onSubmit: (payload: AgentRepositoryListingCreatePayload) => Promise<void>;
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
  const { data: tagLibraries } = useTagLibraries();
  const defaultResourceLibrary = useMemo(
    () =>
      (tagLibraries ?? []).find(
        (library) => library.bucket_key === "default_resource"
      ) ?? null,
    [tagLibraries]
  );
  const { data: tagDefinitions } = useTagDefinitions(
    defaultResourceLibrary?.bucket_id ?? null
  );
  const agentCategory = useMemo(
    () =>
      (tagDefinitions ?? []).find(
        (definition) => definition.definition_key === "agent_category"
      ) ?? null,
    [tagDefinitions]
  );
  const categoryValues = agentCategory?.values ?? [];

  const [selectedIcon, setSelectedIcon] = useState<string | null>(null);
  const [iconInput, setIconInput] = useState("");
  const [iconError, setIconError] = useState<string | null>(null);
  const [presetDropdownOpen, setPresetDropdownOpen] = useState(false);
  const [selectedTagValueIds, setSelectedTagValueIds] = useState<number[]>([]);
  const [listingContent, setListingContent] = useState("");
  const [isSavingTags, setIsSavingTags] = useState(false);
  const [formInitialized, setFormInitialized] = useState(false);

  const agentId = agent?.agent_id;
  const agentTagAssignments = useTagAssignments(
    "agent",
    agentId == null ? null : String(agentId)
  );
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
      categoryValues.map((value) => ({
        label: getAgentRepositoryTagLabel(value.normalized_value, t),
        value: value.value_id,
      })),
    [categoryValues, t]
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
      setFormInitialized(false);
      return;
    }

    if (
      !agent ||
      !isListingsSuccess ||
      tagDefinitions === null ||
      (agentTagAssignments.data === null &&
        agentTagAssignments.error === null) ||
      formInitialized
    ) {
      return;
    }

    if (!agentCategory) {
      clearIconState();
      setSelectedTagValueIds([]);
      setListingContent("");
      setFormInitialized(true);
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
      const assignedIds = new Set(
        (agentTagAssignments.data?.assignments ?? [])
          .filter(
            (assignment) =>
              assignment.definition_id === agentCategory.definition_id
          )
          .map((assignment) => assignment.value_id)
      );
      setSelectedTagValueIds(
        categoryValues
          .filter((value) => assignedIds.has(value.value_id))
          .map((value) => value.value_id)
      );
      setListingContent("");
      setFormInitialized(true);
      return;
    }

    const trimmedIcon = prefill.icon?.trim();
    if (trimmedIcon && isSingleSimpleEmoji(trimmedIcon)) {
      applyIconInputFromValue(trimmedIcon, false);
    } else {
      clearIconState();
    }

    const assignedIds = new Set(
      (agentTagAssignments.data?.assignments ?? [])
        .filter(
          (assignment) =>
            assignment.definition_id === agentCategory.definition_id
        )
        .map((assignment) => assignment.value_id)
    );
    const hasAssignedCategory = assignedIds.size > 0;
    const legacyTags = new Set(
      prefill.tags.map((tag) => tag.trim().toLocaleLowerCase())
    );
    setSelectedTagValueIds(
      categoryValues
        .filter(
          (value) =>
            assignedIds.has(value.value_id) ||
            (!hasAssignedCategory &&
              [
                value.normalized_value,
                value.display_value,
                getAgentRepositoryTagLabel(value.normalized_value, t),
              ].some((candidate) =>
                legacyTags.has(candidate.trim().toLocaleLowerCase())
              ))
        )
        .map((value) => value.value_id)
    );
    setListingContent("");
    setFormInitialized(true);
  }, [
    open,
    agent,
    isListingsSuccess,
    listingsData,
    clearIconState,
    applyIconInputFromValue,
    tagDefinitions,
    agentTagAssignments.data,
    agentTagAssignments.error,
    formInitialized,
    agentCategory,
    categoryValues,
    t,
  ]);

  const title = agent?.name?.trim() || t("agentRepository.card.untitled");

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

  const handleSubmit = async () => {
    if (iconInput.trim() && !isSingleSimpleEmoji(iconInput)) {
      setIconError(invalidIconMessage);
      message.warning(invalidIconMessage);
      return;
    }

    if (!selectedIcon) {
      message.warning(t("agentRepository.mine.applyModal.validation.icon"));
      return;
    }

    const selectedTagValues = categoryValues.filter((value) =>
      selectedTagValueIds.includes(value.value_id)
    );
    if (selectedTagValues.length === 0 || !agentCategory) {
      message.warning(t("agentRepository.mine.applyModal.validation.tags"));
      return;
    }
    if (selectedTagValues.length > MAX_TAGS) {
      message.warning(
        t("agentRepository.mine.applyModal.validation.tagsMax", {
          count: MAX_TAGS,
        })
      );
      return;
    }
    const tags = selectedTagValues.map((value) =>
      resolveAgentRepositoryTagForSubmit(value.normalized_value, t)
    );
    if (tags.some((tag) => tag.length > MAX_TAG_LENGTH)) {
      message.warning(
        t("agentRepository.mine.applyModal.validation.tagLength", {
          count: MAX_TAG_LENGTH,
        })
      );
      return;
    }

    const preservedValueIds = (agentTagAssignments.data?.assignments ?? [])
      .filter(
        (assignment) => assignment.definition_id !== agentCategory.definition_id
      )
      .map((assignment) => assignment.value_id);

    setIsSavingTags(true);
    try {
      await agentTagAssignments.replace({
        value_ids: Array.from(
          new Set([
            ...preservedValueIds,
            ...selectedTagValues.map((value) => value.value_id),
          ])
        ),
      });
      await onSubmit({
        icon: selectedIcon,
        tags,
        content: listingContent.trim(),
      });
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setIsSavingTags(false);
    }
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
          <Button onClick={onClose} disabled={isSubmitting || isSavingTags}>
            {t("common.cancel")}
          </Button>
          <Button
            type="primary"
            loading={isSubmitting || isSavingTags}
            onClick={() => void handleSubmit()}
          >
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
              onChange={(event) => applyIconInputFromValue(event.target.value)}
              maxLength={MAX_ICON_LENGTH}
              status={iconError ? "error" : undefined}
              className="!h-[3.75rem] !w-[6.5rem] shrink-0 !text-4xl"
              styles={{
                root: {
                  display: "inline-flex",
                  alignItems: "center",
                  paddingBlock: 0,
                },
                input: {
                  paddingInline: 2,
                  paddingBlock: 0,
                  textAlign: "center",
                  fontSize: "2.25rem",
                  lineHeight: 1,
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
              mode="multiple"
              className="w-full"
              value={selectedTagValueIds}
              onChange={setSelectedTagValueIds}
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
              {t("repository.mine.applyModal.content")}
            </p>
            <Input.TextArea
              value={listingContent}
              onChange={(event) => setListingContent(event.target.value)}
              rows={4}
              placeholder={t("repository.mine.applyModal.contentPlaceholder")}
            />
          </section>
        </div>
      </Spin>
    </Modal>
  );
}
