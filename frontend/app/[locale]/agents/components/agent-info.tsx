"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Form,
  Button,
  Input,
  Row,
  Col,
  Flex,
  Avatar,
  Upload as AntdUpload,
  message,
  Spin,
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
import { getAgentIcon } from "@/lib/chat/agentIconUtils";
import { useAgentReadOnly } from "@/hooks/agent/useAgentReadOnly";
import ResourceTagAssignmentModal from "@/components/tag/ResourceTagAssignmentModal";
import ResourceTagChips from "@/components/tag/ResourceTagChips";
import TagDefinitionManagementModal from "@/components/tag/TagDefinitionManagementModal";
import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";

export default function AgentInfo() {
  const { t } = useTranslation("common");
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
  const isReadOnly = useAgentReadOnly();
  const [uploading, setUploading] = useState(false);
  const [iconLoadError, setIconLoadError] = useState(false);
  const [iconVersion, setIconVersion] = useState(0);
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
  const DefaultIcon = getAgentIcon({
    id: String(agentId ?? 0),
    agent_id: agentId ?? 0,
    name: editedAgent.name,
    description: editedAgent.description,
  });
  const iconSource =
    agentId !== null && editedAgent.icon_url && !iconLoadError
      ? `${API_ENDPOINTS.agent.icon(agentId)}?v=${iconVersion}`
      : undefined;

  const uploadProps: UploadProps = {
    accept: "image/png,image/jpeg,image/gif,image/webp",
    showUploadList: false,
    beforeUpload: async (file) => {
      const currentAgentId = agentId;
      if (currentAgentId === null) {
        message.error(t("agent.iconUploadRequiresSavedAgent"));
        return AntdUpload.LIST_IGNORE;
      }

      setUploading(true);
      try {
        const formData = new FormData();
        formData.append("file", file);
        const response = await fetchWithAuth(
          API_ENDPOINTS.agent.icon(currentAgentId),
          {
            method: "POST",
            body: formData,
          }
        );
        const data = await response.json();
        setIconLoadError(false);
        setIconVersion(Date.now());
        updateDraft({ icon_url: data.icon_url });
        message.success(t("agent.iconUploadSuccess"));
      } catch {
        message.error(t("agent.iconUploadFailed"));
      } finally {
        setUploading(false);
      }
      return false;
    },
  };

  return (
    <div className="w-full">
      <Row gutter={[16, 0]}>
        {/* Left: text fields */}
        <Col xs={24} md={18}>
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
                  placeholder={t("agent.namePlaceholder")}
                  maxLength={AGENT_NAME_MAX_LENGTH}
                  showCount
                  onChange={(event) =>
                    updateDraftValue("name", event.target.value)
                  }
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
                  placeholder={t("agent.authorPlaceholder")}
                  value={editedAgent.author}
                  onChange={(event) =>
                    updateDraft({ author: event.target.value })
                  }
                />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            label={t("agent.description")}
            className="mb-0"
            name="description"
            rules={[
              {
                required: true,
                message: t("agent.validation.descriptionRequired"),
              },
              {
                max: AGENT_DESCRIPTION_MAX_LENGTH,
                message: t("agent.validation.descriptionMaxLength", {
                  max: AGENT_DESCRIPTION_MAX_LENGTH,
                }),
              },
            ]}
          >
            <Input.TextArea
              placeholder={t("agent.descriptionPlaceholder")}
              rows={3}
              onChange={(event) =>
                updateDraftValue("description", event.target.value)
              }
              showCount
              maxLength={AGENT_DESCRIPTION_MAX_LENGTH}
            />
          </Form.Item>
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
                    emptyText={
                      <span className="text-sm text-slate-400">—</span>
                    }
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
        </Col>

        {/* Right: icon upload */}
        <Col xs={24} md={6}>
          <Flex vertical align="center" className="h-full">
            <div className="mb-2 text-xs text-gray-500 font-medium">
              {t("agent.icon")}
            </div>
            <AntdUpload {...uploadProps}>
              <div
                className="relative group cursor-pointer"
                role="button"
                tabIndex={0}
              >
                <Avatar
                  size={72}
                  src={iconSource}
                  icon={<DefaultIcon size={28} />}
                  onError={() => {
                    setIconLoadError(true);
                    return false;
                  }}
                  className={`border-2 border-dashed border-gray-300 ${iconSource ? "" : "!bg-primary/10 !text-primary"}`}
                />
                <div className="absolute inset-0 flex items-center justify-center rounded-full bg-black/40 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity">
                  {uploading ? (
                    <Spin size="small" />
                  ) : (
                    <Upload size={18} className="text-white" />
                  )}
                </div>
              </div>
            </AntdUpload>

            <div className="mt-2 text-xs text-gray-400 text-center">
              {t("agent.iconHint")}
            </div>
          </Flex>
        </Col>
      </Row>
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
