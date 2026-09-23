"use client";

import { createElement, useEffect, useMemo, useState } from "react";
import {
  App,
  Avatar,
  Button,
  Input,
  Modal,
  Spin,
  Upload as AntdUpload,
} from "antd";
import type { UploadProps } from "antd";
import { Share2, Upload as UploadIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { API_ENDPOINTS } from "@/services/api";
import { fetchWithAuth } from "@/lib/auth";
import { useAgentRepositoryListings } from "@/hooks/agentRepository/useAgentRepositoryListings";
import {
  getAgentRepositoryTagLabel,
  resolveAgentRepositoryTagForSubmit,
} from "@/lib/agentRepositoryLabels";
import { getAgentIcon } from "@/lib/chat/agentIconUtils";
import { withBasePath } from "@/lib/basePath";
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

  const [iconUrl, setIconUrl] = useState<string | null>(null);
  const [iconPreviewUrl, setIconPreviewUrl] = useState<string | null>(null);
  const [iconLoadError, setIconLoadError] = useState(false);
  const [selectedIconFile, setSelectedIconFile] = useState<File | null>(null);
  const [uploadingIcon, setUploadingIcon] = useState(false);
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
        ].some((candidate) =>
          legacyTags.has(candidate.trim().toLocaleLowerCase())
        )
      )
      .map((value) => value.value_id);
    return valueIds.length > 0
      ? { [agentCategory.definition_id]: valueIds }
      : {};
  }, [
    agent?.version_label,
    agentCategory,
    categoryAssignmentValueIds.size,
    categoryValues,
    listingsData?.items,
    t,
  ]);

  useEffect(() => {
    if (!open) {
      setFormInitialized(false);
      setTagEditorOpen(false);
      setSavedAssignments(null);
      setIconPreviewUrl(null);
      setIconLoadError(false);
      setSelectedIconFile(null);
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
      setIconUrl(null);
      setIconPreviewUrl(null);
      setIconLoadError(false);
      setSelectedIconFile(null);
      setListingContent("");
      setFormInitialized(true);
      return;
    }

    setIconUrl(prefill.icon_url);
    setIconPreviewUrl(null);
    setIconLoadError(false);
    setSelectedIconFile(null);

    setListingContent("");
    setFormInitialized(true);
  }, [open, agent, isListingsSuccess, listingsData, formInitialized]);

  const title = agent?.name?.trim() || t("agentRepository.card.untitled");

  useEffect(() => {
    return () => {
      if (iconPreviewUrl) URL.revokeObjectURL(iconPreviewUrl);
    };
  }, [iconPreviewUrl]);

  const handleIconUpload = (file: File) => {
    if (file.size > 2 * 1024 * 1024) {
      message.error(t("agentRepository.mine.applyModal.iconTooLarge"));
      return false;
    }
    setSelectedIconFile(file);
    setIconPreviewUrl(URL.createObjectURL(file));
    setIconLoadError(false);
    return false;
  };

  const uploadProps: UploadProps = {
    accept: "image/png,image/jpeg,image/gif,image/webp",
    showUploadList: false,
    disabled: uploadingIcon || isSubmitting,
    beforeUpload: handleIconUpload,
  };
  const defaultIcon = createElement(getAgentIcon({ agent_id: agentId ?? 0 }), {
    size: 28,
  });
  const selectedIconSource = iconPreviewUrl ?? iconUrl;
  const iconSource =
    selectedIconSource && !iconLoadError
      ? withBasePath(selectedIconSource)
      : undefined;

  const handleSubmit = async () => {
    if (uploadingIcon) {
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
      let submittedIconUrl = iconUrl;
      if (selectedIconFile && agentId != null && agent) {
        setUploadingIcon(true);
        try {
          const formData = new FormData();
          formData.append("file", selectedIconFile);
          const response = await fetchWithAuth(
            API_ENDPOINTS.agentRepository.icon(
              agentId,
              agent.current_version_no ?? 0
            ),
            { method: "POST", body: formData }
          );
          if (!response.ok) throw new Error("Icon upload failed");
          const data = (await response.json()) as { icon_url: string };
          submittedIconUrl = data.icon_url;
          setIconUrl(submittedIconUrl);
          setSelectedIconFile(null);
        } catch {
          message.error(t("agentRepository.mine.applyModal.iconUploadFailed"));
          return;
        }
      }
      await onSubmit({
        icon_url: submittedIconUrl,
        tags,
        content: listingContent.trim(),
      });
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setUploadingIcon(false);
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
            <Button onClick={onClose} disabled={isSubmitting || uploadingIcon}>
              {t("common.cancel")}
            </Button>
            <Button
              type="primary"
              loading={isSubmitting || uploadingIcon}
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
              <div className="mb-2 text-xs font-medium text-gray-500">
                {t("agent.icon")}
              </div>
              <div className="flex flex-col items-start">
                <AntdUpload {...uploadProps}>
                  <div
                    className="group relative cursor-pointer"
                    role="button"
                    tabIndex={0}
                    aria-label={t("agentRepository.mine.applyModal.uploadIcon")}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        event.currentTarget.click();
                      }
                    }}
                  >
                    <Avatar
                      size={72}
                      src={iconSource}
                      icon={defaultIcon}
                      onError={() => {
                        setIconLoadError(true);
                        return false;
                      }}
                      className={`border-2 border-dashed border-gray-300 ${iconSource ? "" : "!bg-primary/10 !text-primary"}`}
                    />
                    <div className="absolute inset-0 flex items-center justify-center rounded-full bg-black/40 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                      {uploadingIcon ? (
                        <Spin size="small" />
                      ) : (
                        <UploadIcon size={18} className="text-white" />
                      )}
                    </div>
                  </div>
                </AntdUpload>
                <div className="mt-2 text-center text-xs text-gray-400">
                  {t("agent.iconHint")}
                </div>
                {(iconUrl || selectedIconFile) && (
                  <Button
                    type="link"
                    size="small"
                    className="!px-0"
                    onClick={() => {
                      setIconUrl(null);
                      setIconPreviewUrl(null);
                      setSelectedIconFile(null);
                      setIconLoadError(false);
                    }}
                    disabled={uploadingIcon || isSubmitting}
                  >
                    {t("agentRepository.mine.applyModal.useDefaultIcon")}
                  </Button>
                )}
              </div>
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
