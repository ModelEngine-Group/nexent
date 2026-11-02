// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { createElement, useRef, useState, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import {
  Form,
  App,
  Button,
  Input,
  Row,
  Col,
  Flex,
  Avatar,
  Upload as AntdUpload,
  Spin,
  Tooltip,
} from "antd";
import type { UploadProps } from "antd";
import { Upload } from "lucide-react";

import { useAgentStore, type AgentDraftPatch } from "@/stores/agentStore";
import {
  AGENT_DESCRIPTION_MAX_LENGTH,
  AGENT_DISPLAY_NAME_MAX_LENGTH,
  AGENT_NAME_MAX_LENGTH,
  createAgentNameConflictValidator,
  isValidAgentName,
} from "@/hooks/agent/useSaveGuard";
import { API_ENDPOINTS } from "@/services/api";
import { fetchWithAuth } from "@/lib/auth";
import {
  DEFAULT_AGENT_ICONS,
  getAgentIcon,
  type DefaultAgentIconKey,
  getAgentUploadedIconRevision,
} from "@/lib/chat/agentIconUtils";
import { useAgentReadOnly } from "@/hooks/agent/useAgentReadOnly";
import ResourceTagAssignmentModal from "@/components/tag/ResourceTagAssignmentModal";
import ResourceTagChips from "@/components/tag/ResourceTagChips";
import TagDefinitionManagementModal from "@/components/tag/TagDefinitionManagementModal";
import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";
import HighFidelityTextArea from "./HighFidelityTextArea";
import AgentAvatarOptions from "./agent-avatar-options";
import { createAgentIconFile } from "@/lib/chat/agentIconImage";

const HIGH_FIDELITY_DESCRIPTION_LIMIT = 200;

interface AgentInfoProps {
  highFidelity?: boolean;
}

export default function AgentInfo({ highFidelity = false }: AgentInfoProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const form = Form.useFormInstance();
  const editedAgent = useAgentStore((state) => state.editedAgent!);
  const updateDraft = useAgentStore((state) => state.updateDraft);

  const updateDraftValue = (
    field: "display_name" | "name" | "description",
    value: string
  ) => {
    form.setFieldValue(field, value);
    updateDraft({ [field]: value } as AgentDraftPatch);
  };

  const agentId = useAgentStore((state) => state.agentId);
  const [descriptionBaseline, setDescriptionBaseline] = useState({
    agentId,
    limit: Math.max(
      HIGH_FIDELITY_DESCRIPTION_LIMIT,
      editedAgent.description?.length ?? 0
    ),
  });
  if (descriptionBaseline.agentId !== agentId) {
    setDescriptionBaseline({
      agentId,
      limit: Math.max(
        HIGH_FIDELITY_DESCRIPTION_LIMIT,
        editedAgent.description?.length ?? 0
      ),
    });
  }
  const isReadOnly = useAgentReadOnly();
  const [uploading, setUploading] = useState(false);
  const uploadInProgress = useRef(false);
  const [avatarSelection, setAvatarSelection] = useState<{
    agentId: number;
    iconUrl: string;
    key: DefaultAgentIconKey;
  } | null>(null);
  const [iconLoadError, setIconLoadError] = useState(false);
  const [assignTagsOpen, setAssignTagsOpen] = useState(false);
  const [tagManagementOpen, setTagManagementOpen] = useState(false);
  const [tagPreviewRefreshKey, setTagPreviewRefreshKey] = useState(0);
  const { data: tagLibraries } = useTagLibraries();
  const defaultTagLibrary =
    tagLibraries?.find(
      (library) => library.bucket_key === "default_resource"
    ) ?? null;
  const { data: tagDefinitions, refresh: refreshTagDefinitions } =
    useTagDefinitions(defaultTagLibrary?.bucket_id ?? null);
  const defaultIcon = createElement(
    getAgentIcon({
      id: String(agentId ?? 0),
      agent_id: agentId ?? 0,
      name: editedAgent.name,
      description: editedAgent.description,
    }),
    { size: highFidelity ? 56 : 28 }
  );
  const iconSource =
    agentId !== null && editedAgent.icon_url && !iconLoadError
      ? API_ENDPOINTS.agent.icon(
          agentId,
          getAgentUploadedIconRevision(editedAgent.icon_url)
        )
      : undefined;

  const selectedIconKey = editedAgent.icon_url
    ? avatarSelection?.agentId === agentId &&
      avatarSelection.iconUrl === editedAgent.icon_url
      ? avatarSelection.key
      : null
    : DEFAULT_AGENT_ICONS.find(
        (option) => option.icon === getAgentIcon({ agent_id: agentId ?? 0 })
      )?.key;

  const uploadIcon = async (
    source: File | (() => Promise<File>),
    presetKey?: DefaultAgentIconKey
  ) => {
    if (isReadOnly || uploadInProgress.current) return;
    const currentAgentId = agentId;
    if (currentAgentId === null) {
      message.error(t("agent.iconUploadRequiresSavedAgent"));
      return;
    }
    uploadInProgress.current = true;
    setUploading(true);
    try {
      const file = typeof source === "function" ? await source() : source;
      if (
        !["image/png", "image/jpeg", "image/gif", "image/webp"].includes(
          file.type
        ) ||
        file.size >= 2 * 1024 * 1024
      ) {
        message.error(t("agent.highFidelity.invalidAvatar"));
        return;
      }
      if (useAgentStore.getState().agentId !== currentAgentId) return;
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetchWithAuth(
        API_ENDPOINTS.agent.icon(currentAgentId),
        {
          method: "POST",
          body: formData,
        }
      );
      if (!response.ok) throw new Error("Agent icon upload failed");
      const data = await response.json();
      if (typeof data.icon_url !== "string" || !data.icon_url.trim()) {
        throw new Error("Agent icon upload returned no image URL");
      }
      if (useAgentStore.getState().agentId !== currentAgentId) return;
      setIconLoadError(false);
      updateDraft({ icon_url: data.icon_url });
      setAvatarSelection(
        presetKey
          ? { agentId: currentAgentId, iconUrl: data.icon_url, key: presetKey }
          : null
      );
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      message.success(t("agent.iconUploadSuccess"));
    } catch {
      message.error(t("agent.iconUploadFailed"));
    } finally {
      uploadInProgress.current = false;
      setUploading(false);
    }
  };
  const uploadProps: UploadProps = {
    accept: "image/png,image/jpeg,image/gif,image/webp",
    showUploadList: false,
    disabled: isReadOnly || uploading,
    beforeUpload: async (file) => {
      await uploadIcon(file);
      return false;
    },
  };

  const identityFields = (
    <>
      <Row gutter={[12, 0]}>
        <Col
          xs={24}
          sm={12}
          className={
            highFidelity
              ? "!max-w-full !flex-[0_0_100%] @min-[640px]/agent-config:!max-w-1/2 @min-[640px]/agent-config:!flex-[0_0_50%]"
              : undefined
          }
        >
          <Form.Item
            label={t("agent.displayName")}
            className="mb-3"
            name="display_name"
            validateTrigger={["onChange", "onBlur"]}
            rules={[
              {
                required: true,
                message: t("agent.validation.displayNameRequired"),
              },
              {
                max: AGENT_DISPLAY_NAME_MAX_LENGTH,
                message: t("agent.validation.displayNameMaxLength", {
                  max: AGENT_DISPLAY_NAME_MAX_LENGTH,
                }),
              },
              {
                ...createAgentNameConflictValidator(
                  t,
                  "display_name",
                  agentId ?? undefined
                ),
                validateTrigger: "onBlur",
              },
            ]}
          >
            <Input
              disabled={isReadOnly}
              placeholder={t("agent.displayNamePlaceholder")}
              maxLength={AGENT_DISPLAY_NAME_MAX_LENGTH}
              showCount
              onChange={(event) =>
                updateDraftValue("display_name", event.target.value)
              }
            />
          </Form.Item>
        </Col>
        <Col
          xs={24}
          sm={12}
          className={
            highFidelity
              ? "!max-w-full !flex-[0_0_100%] @min-[640px]/agent-config:!max-w-1/2 @min-[640px]/agent-config:!flex-[0_0_50%]"
              : undefined
          }
        >
          <Form.Item
            label={t("agent.name")}
            className="mb-3"
            name="name"
            validateTrigger={["onChange", "onBlur"]}
            rules={[
              {
                required: true,
                message: t("agent.validation.nameRequired"),
              },
              {
                validator: (_, value: string) =>
                  !value || isValidAgentName(value)
                    ? Promise.resolve()
                    : Promise.reject(
                        new Error(t("agent.validation.namePattern"))
                      ),
              },
              {
                ...createAgentNameConflictValidator(
                  t,
                  "name",
                  agentId ?? undefined
                ),
                validateTrigger: "onBlur",
              },
            ]}
          >
            <Input
              data-testid="agent-variable-name-input"
              disabled={isReadOnly}
              placeholder={t("agent.namePlaceholder")}
              count={{
                max: AGENT_NAME_MAX_LENGTH,
                strategy: (value) => Array.from(value).length,
              }}
              showCount
              onChange={(event) => updateDraftValue("name", event.target.value)}
            />
          </Form.Item>
        </Col>
      </Row>
    </>
  );

  const descriptionTextAreaProps = {
    placeholder: t(
      highFidelity
        ? "agent.highFidelity.descriptionPlaceholder"
        : "agent.descriptionPlaceholder"
    ),
    "aria-label": t("agent.description"),
    rows: 3,
    disabled: isReadOnly,
    onChange: (event: ChangeEvent<HTMLTextAreaElement>) =>
      updateDraftValue("description", event.target.value),
  };
  const descriptionField = (
    <Form.Item
      label={
        highFidelity ? (
          <span className="text-sm font-normal leading-[22px] tracking-[0px] text-[#191919] [font-family:'HarmonyOS_Sans_SC',sans-serif]">
            {t("agent.description")}
          </span>
        ) : (
          t("agent.description")
        )
      }
      className={
        highFidelity
          ? "!mb-0 [&_.ant-form-item-label]:!pb-2 [&_.ant-form-item-label>label]:!h-[22px]"
          : "mb-0"
      }
      name="description"
      required={highFidelity ? false : undefined}
      rules={[
        {
          required: true,
          message: t("agent.validation.descriptionRequired"),
        },
        {
          max: highFidelity
            ? descriptionBaseline.limit
            : AGENT_DESCRIPTION_MAX_LENGTH,
          message: t("agent.validation.descriptionMaxLength", {
            max: highFidelity
              ? HIGH_FIDELITY_DESCRIPTION_LIMIT
              : AGENT_DESCRIPTION_MAX_LENGTH,
          }),
        },
      ]}
    >
      {highFidelity ? (
        <HighFidelityTextArea
          {...descriptionTextAreaProps}
          limit={HIGH_FIDELITY_DESCRIPTION_LIMIT}
          classNames={{
            root: "!h-[100px] !rounded-[4px] !border-[#c9c9c9]",
            textarea:
              "!h-[98px] !min-h-[98px] !resize-none !rounded-[4px] !px-3 !py-[5px] !text-sm !leading-[22px] !tracking-[0px] !text-[#191919] [font-family:'HarmonyOS_Sans_SC',sans-serif]",
            count:
              "!bottom-2 !right-3 !text-xs !leading-[22px] !text-[#808080]",
          }}
        />
      ) : (
        <Input.TextArea
          {...descriptionTextAreaProps}
          showCount
          maxLength={AGENT_DESCRIPTION_MAX_LENGTH}
        />
      )}
    </Form.Item>
  );

  const tagFields = (
    <Form.Item
      label={t("tagManagement.title.assignTags")}
      className="mb-0 mt-3"
    >
      <div className="flex min-w-0 items-center gap-2">
        <div className="min-w-0 flex-1 overflow-hidden whitespace-nowrap [&>span]:gap-2 [&_.ant-tag]:!m-0 [&_.ant-tag]:!h-[26px] [&_.ant-tag]:!rounded-full [&_.ant-tag]:!border-0 [&_.ant-tag]:!bg-[#E6F2FD] [&_.ant-tag]:!px-2.5 [&_.ant-tag]:!text-[12px] [&_.ant-tag]:!leading-[26px] [&_.ant-tag]:!text-[#0067D1]">
          {agentId !== null ? (
            <ResourceTagChips
              resourceType="agent"
              resourceId={String(agentId)}
              max={4}
              refreshKey={tagPreviewRefreshKey}
              singleLine
              emptyText={<span className="text-sm text-slate-400">—</span>}
            />
          ) : (
            <span className="text-sm text-slate-400">—</span>
          )}
        </div>
        <Button
          type="link"
          size="small"
          disabled={agentId === null || isReadOnly}
          onClick={() => setAssignTagsOpen(true)}
        >
          {t("tagManagement.action.editTags")}
        </Button>
      </div>
    </Form.Item>
  );

  const avatarField = (
    <Flex
      vertical
      align={highFidelity ? "flex-start" : "center"}
      className={highFidelity ? "min-h-[130px] items-start gap-2" : "h-full"}
    >
      <Tooltip title={highFidelity ? t("agent.iconHint") : undefined}>
        <div
          className={
            highFidelity
              ? "text-sm font-normal leading-[22px] tracking-[0px] text-[#191919] [font-family:'HarmonyOS_Sans_SC',sans-serif]"
              : "mb-2 text-xs text-gray-500 font-medium"
          }
        >
          {t(highFidelity ? "agent.highFidelity.avatar" : "agent.icon")}
        </div>
      </Tooltip>
      <div className="flex min-w-0 items-start gap-3">
        <AntdUpload {...uploadProps}>
          <div
            className="relative group cursor-pointer"
            role="button"
            aria-label={t("agent.icon")}
            aria-disabled={isReadOnly || uploading}
            tabIndex={isReadOnly ? -1 : 0}
          >
            <Avatar
              size={highFidelity ? 100 : 72}
              shape={highFidelity ? "square" : "circle"}
              src={iconSource}
              icon={defaultIcon}
              onError={() => {
                setIconLoadError(true);
                return false;
              }}
              className={`${highFidelity ? "!flex !items-center !justify-center !rounded-lg !border !border-solid !border-[#c9c9c9]" : "border-2 border-dashed border-gray-300"} ${iconSource ? "!bg-white" : "!bg-primary/10 !text-primary"}`}
            />
            <div
              className={`absolute inset-0 flex items-center justify-center ${highFidelity ? "rounded-lg" : "rounded-full"} bg-black/40 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity`}
            >
              {uploading ? (
                <Spin size="small" />
              ) : (
                <Upload size={18} className="text-white" />
              )}
            </div>
          </div>
        </AntdUpload>
        {highFidelity && (
          <div className="flex min-w-0 flex-1 flex-col gap-3">
            <span className="text-xs leading-[22px] text-[#808080]">
              {t("agent.highFidelity.avatarHint")}
            </span>
            <AgentAvatarOptions
              disabled={agentId === null || isReadOnly || uploading}
              selectedKey={selectedIconKey}
              onSelect={(key, svg) =>
                void uploadIcon(() => createAgentIconFile(svg), key)
              }
            />
          </div>
        )}
      </div>

      {!highFidelity && (
        <div className="mt-2 text-xs text-gray-400 text-center">
          {t("agent.iconHint")}
        </div>
      )}
    </Flex>
  );

  return (
    <div className="w-full">
      {highFidelity ? (
        <>
          <div className="grid min-w-0 grid-cols-1 gap-4 @min-[640px]/agent-config:grid-cols-2">
            <div className="min-w-0">{descriptionField}</div>
            <div className="min-w-0">{avatarField}</div>
          </div>
          <div className="mt-4">{identityFields}</div>
        </>
      ) : (
        <Row gutter={[16, 0]}>
          <Col xs={24} md={18}>
            {identityFields}
            {descriptionField}
          </Col>
          <Col xs={24} md={6}>
            {avatarField}
          </Col>
        </Row>
      )}
      {tagFields}
      <ResourceTagAssignmentModal
        open={assignTagsOpen}
        onClose={() => {
          setAssignTagsOpen(false);
          setTagPreviewRefreshKey((current) => current + 1);
        }}
        resourceType="agent"
        resourceId={String(agentId ?? "")}
        definitions={tagDefinitions ?? []}
        canEdit={agentId !== null && !isReadOnly}
        onManageDefinitions={() => setTagManagementOpen(true)}
      />
      <TagDefinitionManagementModal
        open={tagManagementOpen}
        onClose={() => {
          setTagManagementOpen(false);
          void refreshTagDefinitions();
        }}
        bucketId={defaultTagLibrary?.bucket_id ?? 0}
        bucketName={defaultTagLibrary?.bucket_name ?? ""}
        canManage={!isReadOnly}
      />
    </div>
  );
}
