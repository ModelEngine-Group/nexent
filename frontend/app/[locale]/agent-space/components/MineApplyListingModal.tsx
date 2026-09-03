"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { App, Button, Dropdown, Input, Modal, Spin } from "antd";
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
import ResourceTagAssignmentModal from "@/components/tag/ResourceTagAssignmentModal";
import {
  buildApplyListingFormPrefill,
  pickApplyListingPrefillSource,
} from "@/lib/agentRepositoryMine";
import type {
  AgentRepositoryListingCreatePayload,
  MyEditableAgentItem,
} from "@/types/agentRepository";
import type { TagAssignmentValue } from "@/types/tagManagement";

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
  const [listingContent, setListingContent] = useState("");
  const [formInitialized, setFormInitialized] = useState(false);
  const [tagEditorOpen, setTagEditorOpen] = useState(false);
  const [savedAssignments, setSavedAssignments] = useState<
    TagAssignmentValue[] | null
  >(null);

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

  const assignmentValues =
    savedAssignments ?? agentTagAssignments.data?.assignments ?? [];

  const categoryAssignmentValueIds = useMemo(
    () =>
      new Set(
        assignmentValues
          .filter(
            (assignment) =>
              assignment.definition_id === agentCategory?.definition_id
          )
          .map((assignment) => assignment.value_id)
      ),
    [agentCategory?.definition_id, assignmentValues]
  );

  const selectedCategoryValues = useMemo(
    () =>
      categoryValues.filter((value) =>
        categoryAssignmentValueIds.has(value.value_id)
      ),
    [categoryAssignmentValueIds, categoryValues]
  );

  const legacyCategorySelection = useMemo(() => {
    if (!agentCategory || categoryAssignmentValueIds.size > 0) return {};
    const source = pickApplyListingPrefillSource(
      listingsData?.items ?? [],
      agent?.version_label
    );
    const prefill = buildApplyListingFormPrefill(source, { maxTags: MAX_TAGS });
    if (!prefill) return {};
    const legacyTags = new Set(
      prefill.tags.map((tag) => tag.trim().toLocaleLowerCase())
    );
    const valueIds = categoryValues
      .filter((value) =>
        [
          value.normalized_value,
          value.display_value,
          getAgentRepositoryTagLabel(value.normalized_value, t),
        ].some((candidate) => legacyTags.has(candidate.trim().toLocaleLowerCase()))
      )
      .map((value) => value.value_id);
    return valueIds.length > 0 ? { [agentCategory.definition_id]: valueIds } : {};
  }, [
    agent?.version_label,
    agentCategory,
    categoryAssignmentValueIds.size,
    categoryValues,
    listingsData?.items,
    t,
  ]);

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
      setTagEditorOpen(false);
      setSavedAssignments(null);
      return;
    }

    if (!agent || !isListingsSuccess || formInitialized) {
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

    setListingContent("");
    setFormInitialized(true);
  }, [
    open,
    agent,
    isListingsSuccess,
    listingsData,
    clearIconState,
    applyIconInputFromValue,
    formInitialized,
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

    if (selectedCategoryValues.length === 0 || !agentCategory) {
      message.warning(t("agentRepository.mine.applyModal.validation.tags"));
      return;
    }
    if (selectedCategoryValues.length > MAX_TAGS) {
      message.warning(
        t("agentRepository.mine.applyModal.validation.tagsMax", {
          count: MAX_TAGS,
        })
      );
      return;
    }
    const tags = selectedCategoryValues.map((value) =>
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

    try {
      await onSubmit({
        icon: selectedIcon,
        tags,
        content: listingContent.trim(),
      });
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <>
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
          <Button
            type="primary"
            loading={isSubmitting}
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
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={() => setTagEditorOpen(true)}>
                {t("tagManagement.action.editTags")}
              </Button>
              {selectedCategoryValues.length > 0 ? (
                <span className="text-sm text-slate-600 dark:text-slate-300">
                  {selectedCategoryValues
                    .map((value) =>
                      getAgentRepositoryTagLabel(value.normalized_value, t)
                    )
                    .join(" · ")}
                </span>
              ) : null}
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {t("agentRepository.mine.applyModal.tagsHint")}
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
      <ResourceTagAssignmentModal
        open={tagEditorOpen && agentId != null}
        onClose={() => setTagEditorOpen(false)}
        resourceType="agent"
        resourceId={String(agentId ?? "")}
        definitions={tagDefinitions ?? []}
        canEdit={agent?.permission !== "READ_ONLY"}
        initialSelection={legacyCategorySelection}
        onSaved={(assignment) => setSavedAssignments(assignment.assignments)}
      />
    </>
  );
}
