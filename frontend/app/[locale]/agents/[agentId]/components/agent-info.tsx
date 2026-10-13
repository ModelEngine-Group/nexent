"use client";

import { createElement, useState, type ChangeEvent } from "react";
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
  AGENT_NAME_MAX_LENGTH,
  createAgentNameConflictValidator,
  isValidAgentName,
} from "@/hooks/agent/useSaveGuard";
import { API_ENDPOINTS } from "@/services/api";
import { fetchWithAuth } from "@/lib/auth";
import {
  getAgentIcon,
  getAgentUploadedIconRevision,
} from "@/lib/chat/agentIconUtils";
import { useAgentReadOnly } from "@/hooks/agent/useAgentReadOnly";
import ResourceTagAssignmentModal from "@/components/tag/ResourceTagAssignmentModal";
import ResourceTagChips from "@/components/tag/ResourceTagChips";
import TagDefinitionManagementModal from "@/components/tag/TagDefinitionManagementModal";
import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";
import HighFidelityTextArea from "./HighFidelityTextArea";
import {
  DefaultAgentAvatar,
  DEFAULT_AGENT_AVATAR_COLORS,
} from "./DefaultAgentAvatar";

const HIGH_FIDELITY_DESCRIPTION_LIMIT = 200;

interface AgentInfoProps {
  highFidelity?: boolean;
  guideCompact?: boolean;
}

export default function AgentInfo({
  highFidelity = false,
  guideCompact = false,
}: AgentInfoProps) {
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
    { size: 28 }
  );
  const iconSource =
    agentId !== null && editedAgent.icon_url && !iconLoadError
      ? API_ENDPOINTS.agent.icon(
          agentId,
          getAgentUploadedIconRevision(editedAgent.icon_url)
        )
      : undefined;

  const uploadIcon = async (file: File) => {
    if (isReadOnly || uploading) return;
    if (
      !["image/png", "image/jpeg", "image/gif", "image/webp"].includes(
        file.type
      ) ||
      file.size >= 2 * 1024 * 1024
    ) {
      message.error(t("agent.highFidelity.invalidAvatar"));
      return;
    }
    const currentAgentId = agentId;
    if (currentAgentId === null) {
      message.error(t("agent.iconUploadRequiresSavedAgent"));
      return;
    }
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetchWithAuth(
        API_ENDPOINTS.agent.icon(currentAgentId),
        { method: "POST", body: formData }
      );
      if (!response.ok) throw new Error("Agent icon upload failed");
      const data = await response.json();
      if (useAgentStore.getState().agentId !== currentAgentId) return;
      setIconLoadError(false);
      updateDraft({ icon_url: data.icon_url });
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      message.success(t("agent.iconUploadSuccess"));
    } catch {
      message.error(t("agent.iconUploadFailed"));
    } finally {
      setUploading(false);
    }
  };
  const selectDefaultAvatar = async (colors: string[]) => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 200;
    const context = canvas.getContext("2d");
    if (!context) return;
    const gradient = context.createLinearGradient(20, 20, 180, 180);
    colors.forEach((color, index) => gradient.addColorStop(index, color));
    context.fillStyle = gradient;
    context.beginPath();
    context.arc(100, 100, 90, 0, Math.PI * 2);
    context.fill();
    context.fillStyle = "white";
    context.font = "italic bold 110px sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText("n", 100, 98);
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/png")
    );
    if (blob)
      await uploadIcon(
        new File([blob], "default-avatar.png", { type: "image/png" })
      );
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
        <Col xs={24} sm={12}>
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
                max: AGENT_NAME_MAX_LENGTH,
                message: t("agent.validation.displayNameMaxLength", {
                  max: AGENT_NAME_MAX_LENGTH,
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
              maxLength={AGENT_NAME_MAX_LENGTH}
              showCount
              onChange={(event) =>
                updateDraftValue("display_name", event.target.value)
              }
            />
          </Form.Item>
        </Col>
        <Col xs={24} sm={12}>
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
                max: AGENT_NAME_MAX_LENGTH,
                message: t("agent.validation.nameMaxLength", {
                  max: AGENT_NAME_MAX_LENGTH,
                }),
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
              maxLength={AGENT_NAME_MAX_LENGTH}
              showCount
              onChange={(event) => updateDraftValue("name", event.target.value)}
            />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={[12, 0]}>
        <Col xs={24} sm={12}>
          <Form.Item
            label={t("agent.author")}
            className="mb-3"
            name="author"
            rules={[
              {
                required: true,
                message: t("agent.validation.authorRequired"),
              },
            ]}
          >
            <Input
              disabled={isReadOnly}
              placeholder={t("agent.authorPlaceholder")}
              value={editedAgent.author}
              onChange={(event) => updateDraft({ author: event.target.value })}
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
        <div className="min-w-0 flex-1 overflow-hidden whitespace-nowrap">
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
      className={highFidelity ? "h-[130px] items-start gap-2" : "h-full"}
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
              icon={highFidelity ? <DefaultAgentAvatar /> : defaultIcon}
              onError={() => {
                setIconLoadError(true);
                return false;
              }}
              className={`${highFidelity ? "!flex !items-center !justify-center !rounded-lg !bg-white !border !border-solid !border-[#c9c9c9]" : "border-2 border-dashed border-gray-300"} ${iconSource || highFidelity ? "" : "!bg-primary/10 !text-primary"}`}
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
          <div className="flex h-[100px] min-w-0 flex-col justify-between">
            <span className="text-xs leading-[22px] text-[#808080]">
              {t("agent.highFidelity.avatarHint")}
            </span>
            <div className="flex flex-col gap-1">
              <span className="text-xs leading-[22px] text-[#808080]">
                {t("agent.highFidelity.defaultAvatars")}
              </span>
              <div className="flex gap-2">
                {DEFAULT_AGENT_AVATAR_COLORS.map((colors, index) => (
                  <Button
                    key={index}
                    type="text"
                    aria-label={`${t("agent.highFidelity.defaultAvatars")} ${index + 1}`}
                    disabled={isReadOnly || uploading || agentId === null}
                    onClick={() => void selectDefaultAvatar(colors)}
                    className="!h-9 !w-[35px] !rounded-[4px] !p-[3px]"
                  >
                    <DefaultAgentAvatar size={29} colors={colors} />
                  </Button>
                ))}
              </div>
            </div>
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
          <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="min-w-0">{descriptionField}</div>
            <div className="min-w-0">{avatarField}</div>
          </div>
          <div className={guideCompact ? "hidden" : "mt-4"}>
            {identityFields}
            {tagFields}
          </div>
        </>
      ) : (
        <Row gutter={[16, 0]}>
          <Col xs={24} md={18}>
            {identityFields}
            {descriptionField}
            {tagFields}
          </Col>
          <Col xs={24} md={6}>
            {avatarField}
          </Col>
        </Row>
      )}
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
