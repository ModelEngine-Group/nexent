// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useState } from "react";
import {
  App,
  Button,
  ConfigProvider,
  Form,
  Input,
  InputNumber,
  Select,
  Upload,
} from "antd";
import type { UploadFile } from "antd";
import { RefreshCw, Upload as UploadIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { McpDeploymentType, McpTransportType } from "@/const/mcpTools";
import type { LocalAddMcpDraft } from "@/types/mcpTools";
import { useMcpAddLocal } from "@/hooks/mcpTools/useMcpAddLocal";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import McpGroupSelectionTable from "../../shared/McpGroupSelectionTable";
import McpDeploymentCards from "../../shared/McpDeploymentCards";
import McpConfigurationSteps from "../../shared/McpConfigurationSteps";
import { usePermission } from "@/hooks/permission/usePermission";
import { Can } from "@/components/permission/Can";
import McpContainerLogsModal from "@/components/mcp/McpContainerLogsModal";
import ResourceTagAssignmentModal from "@/components/tag/ResourceTagAssignmentModal";
import TagChips from "@/components/tag/TagChips";
import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";
import McpTagField from "../../shared/McpTagField";
import { testMcpConnectionService } from "@/services/mcpToolsService";

const VALIDATION_FIELDS_BY_DEPLOYMENT: Record<
  McpDeploymentType,
  Array<keyof LocalAddMcpDraft>
> = {
  [McpDeploymentType.REMOTE_LINK]: [
    "name",
    "description",
    "serverUrl",
    "authorizationToken",
    "customHeaders",
  ],
  [McpDeploymentType.CONTAINER]: [
    "name",
    "description",
    "containerConfigJson",
    "authorizationToken",
  ],
  [McpDeploymentType.API]: [
    "name",
    "description",
    "serverUrl",
    "customHeaders",
    "openApiJson",
  ],
  [McpDeploymentType.LOCAL_IMAGE]: [
    "name",
    "description",
    "uploadImageFile",
    "authorizationToken",
  ],
};

const createInitialDraft = (): LocalAddMcpDraft => ({
  name: "",
  description: "",
  deploymentType: McpDeploymentType.REMOTE_LINK,
  transportType: McpTransportType.URL,
  serverUrl: "",
  authorizationToken: "",
  customHeaders: "",
  openApiJson: "",
  containerConfigJson: "",
  containerPort: undefined,
  uploadImageFile: null,
  tags: [],
  groupIds: [],
  ingroupPermission: "READ_ONLY",
});

interface AddMcpServiceLocalSectionProps {
  active: boolean;
  enableUploadImage?: boolean;
  onAdded: () => void;
  onClose: () => void;
  onSubmittingChange?: (submitting: boolean) => void;
}

export default function AddMcpServiceLocalSection({
  active,
  enableUploadImage = false,
  onAdded,
  onClose,
  onSubmittingChange,
}: AddMcpServiceLocalSectionProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const rules = useMcpFormRules();
  const [form] = Form.useForm();
  const [draft, setDraft] = useState<LocalAddMcpDraft>(() =>
    createInitialDraft()
  );
  const [deploymentType, setDeploymentType] = useState<McpDeploymentType>(
    McpDeploymentType.REMOTE_LINK
  );
  const [deploymentStarted, setDeploymentStarted] = useState(false);
  const [deployedContainerId, setDeployedContainerId] = useState<string | null>(
    null
  );
  const [logsOpen, setLogsOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [testingConnection, setTestingConnection] = useState(false);
  const [tagsOpen, setTagsOpen] = useState(false);
  const [tagSelection, setTagSelection] = useState<Record<number, number[]>>(
    {}
  );
  const tagLibraries = useTagLibraries({ enabled: tagsOpen });
  const defaultTagLibrary = tagLibraries.data?.find(
    (library) => library.bucket_key === "default_resource"
  );
  const tagDefinitions = useTagDefinitions(
    defaultTagLibrary?.bucket_id ?? null
  );
  const selectedTags = (tagDefinitions.data ?? []).flatMap((definition) =>
    (definition.values ?? [])
      .filter((value) =>
        tagSelection[definition.definition_id]?.includes(value.value_id)
      )
      .map((value) => ({
        definition_id: definition.definition_id,
        definition_key: definition.definition_key,
        definition_name: definition.definition_name,
        selection_mode: definition.selection_mode,
        value_id: value.value_id,
        display_value: value.display_value,
        value_status: value.status,
      }))
  );
  const { isReady, can } = usePermission();
  const canSelectGroups = isReady && can("group:read");
  const { user } = useAuthorizationContext();
  const tenantId = user?.tenantId || null;
  const { data: groupData, isLoading: loadingGroups } = useGroupList(tenantId);
  const groups = groupData?.groups || [];
  const { submit, submitting } = useMcpAddLocal({
    onSuccess: () => {
      setDraft(createInitialDraft());
      setDeploymentType(McpDeploymentType.REMOTE_LINK);
      setTagSelection({});
      form.resetFields();
      onAdded();
    },
    onContainerStarted: (containerId) => setDeployedContainerId(containerId),
  });

  // Notify parent modal of submitting state to block close during submission
  useEffect(() => {
    onSubmittingChange?.(submitting);
  }, [submitting, onSubmittingChange]);

  const patchDraft = (patch: Partial<LocalAddMcpDraft>) => {
    setDraft((prev) => ({ ...prev, ...patch }));
  };

  const handleDeploymentChange = (nextType: McpDeploymentType) => {
    const nextTransport =
      nextType === McpDeploymentType.CONTAINER ||
      nextType === McpDeploymentType.LOCAL_IMAGE
        ? McpTransportType.CONTAINER
        : McpTransportType.URL;
    patchDraft({
      deploymentType: nextType,
      transportType: nextTransport,
      uploadImageFile:
        nextType === McpDeploymentType.LOCAL_IMAGE
          ? draft.uploadImageFile
          : null,
      groupIds: draft.groupIds,
      ingroupPermission: "READ_ONLY" as "EDIT" | "READ_ONLY" | "PRIVATE",
    });
    setDeploymentType(nextType);
    form.setFieldValue("transportType", nextTransport);
  };

  const uploadFileList: UploadFile[] = draft.uploadImageFile
    ? [
        {
          uid: "local-image",
          name: draft.uploadImageFile.name,
          status: "done",
          originFileObj: draft.uploadImageFile as UploadFile["originFileObj"],
        },
      ]
    : [];

  const bindField = <K extends keyof LocalAddMcpDraft>(key: K) => ({
    value: draft[key],
    onChange: (eventOrValue: unknown) => {
      const next =
        eventOrValue &&
        typeof eventOrValue === "object" &&
        "target" in (eventOrValue as Record<string, unknown>)
          ? (eventOrValue as { target: { value: LocalAddMcpDraft[K] } }).target
              .value
          : (eventOrValue as LocalAddMcpDraft[K]);
      patchDraft({ [key]: next } as Partial<LocalAddMcpDraft>);
      form.setFieldValue(key as string, next);
    },
  });

  const handlePermissionChange = (value: string) => {
    const permission = value as "EDIT" | "READ_ONLY" | "PRIVATE";
    patchDraft({ ingroupPermission: permission });
    if (permission === "PRIVATE") {
      patchDraft({ groupIds: [] });
    }
  };

  const validateConfiguration = async () => {
    try {
      await form.validateFields(
        VALIDATION_FIELDS_BY_DEPLOYMENT[deploymentType]
      );
    } catch {
      return false;
    }
    return true;
  };

  const handleSubmit = async () => {
    if (!(await validateConfiguration())) return;
    const isContainerDeployment =
      deploymentType === McpDeploymentType.CONTAINER ||
      deploymentType === McpDeploymentType.LOCAL_IMAGE;
    if (isContainerDeployment) {
      setDeploymentStarted(true);
      setDeployedContainerId(null);
    }
    await submit(draft, Object.values(tagSelection).flat());
  };

  const handleTestConnection = async () => {
    setTestingConnection(true);
    try {
      const values = await form
        .validateFields(["serverUrl", "customHeaders", "authorizationToken"])
        .catch(() => null);
      if (!values) return;

      const headers = values.customHeaders?.trim();
      const result = await testMcpConnectionService({
        server_url: values.serverUrl.trim(),
        authorization_token: values.authorizationToken?.trim() || undefined,
        custom_headers: headers ? JSON.parse(headers) : undefined,
      });
      if (result.data.success) {
        message.success(
          t("mcpTools.registry.quickAddPicker.connectionSuccess")
        );
      } else {
        message.error(t("mcpTools.add.error.connectionFailed"));
      }
    } finally {
      setTestingConnection(false);
    }
  };

  if (!active) return null;

  const isApi = deploymentType === McpDeploymentType.API;
  const isContainer = deploymentType === McpDeploymentType.CONTAINER;
  const isLocalImage = deploymentType === McpDeploymentType.LOCAL_IMAGE;
  const isRemote = deploymentType === McpDeploymentType.REMOTE_LINK;
  const isGroupSelectDisabled = draft.ingroupPermission === "PRIVATE" || isApi;
  const urlPlaceholder = isApi
    ? "mcpConfig.openapiService.form.serverUrlPlaceholder"
    : "mcpConfig.addServer.urlPlaceholder";
  const jsonField = isApi ? "openApiJson" : "containerConfigJson";
  const showGroupStep = canSelectGroups && step === 1;

  return (
    <ConfigProvider
      theme={{
        token: {
          borderRadius: 4,
          colorBorder: "#c9c9c9",
          colorPrimary: "#0067d1",
          colorText: "#191919",
          colorTextPlaceholder: "#aeaeae",
          controlHeight: 32,
        },
        components: {
          Form: { itemMarginBottom: 16, verticalLabelPadding: "0 0 8px" },
        },
      }}
    >
      <div className="flex min-h-0 flex-1 flex-col gap-4 pt-4">
        {canSelectGroups && <McpConfigurationSteps current={step} />}
        <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-width:thin]">
          <Form form={form} layout="vertical" colon={false}>
            <div hidden={showGroupStep}>
              <McpDeploymentCards
                ariaLabel={t("mcpTools.addModal.configureStep")}
                value={deploymentType}
                includeLocalImage={enableUploadImage}
                onChange={handleDeploymentChange}
                className="!mb-4"
              />
              <Form.Item
                label={t("mcpTools.addModal.name")}
                name="name"
                rules={rules.name}
              >
                <Input
                  placeholder={t("mcpTools.addModal.namePlaceholder")}
                  {...bindField("name")}
                  maxLength={20}
                  autoComplete="off"
                />
              </Form.Item>
              <Form.Item
                label={t("common.description")}
                name="description"
                rules={rules.description}
              >
                <Input.TextArea
                  placeholder={t("mcpTools.detail.serviceDescription")}
                  {...bindField("description")}
                  rows={4}
                />
              </Form.Item>
              {(isRemote || isApi) && (
                <Form.Item
                  label={t(
                    isApi
                      ? "mcpConfig.openapiService.form.serverUrl"
                      : "mcpTools.addModal.serverUrl"
                  )}
                  name="serverUrl"
                  rules={rules.httpUrl}
                >
                  <Input
                    placeholder={t(urlPlaceholder)}
                    {...bindField("serverUrl")}
                    autoComplete="off"
                  />
                </Form.Item>
              )}
              {isLocalImage && (
                <Form.Item
                  label={t("mcpConfig.uploadImage.title")}
                  name="uploadImageFile"
                  extra={t("mcpConfig.uploadImage.fileHint")}
                  rules={[
                    {
                      required: true,
                      message: t("mcpConfig.message.uploadImageFileRequired"),
                    },
                    {
                      validator: async (_, value: File | null) => {
                        if (value?.name && !value.name.endsWith(".tar")) {
                          throw new Error(
                            t("mcpConfig.message.uploadImageInvalidFileType")
                          );
                        }
                      },
                    },
                  ]}
                >
                  <Upload
                    beforeUpload={() => false}
                    accept=".tar"
                    maxCount={1}
                    fileList={uploadFileList}
                    onRemove={() => {
                      patchDraft({ uploadImageFile: null });
                      form.setFieldValue("uploadImageFile", null);
                    }}
                    onChange={(info) => {
                      const file = info.fileList[0]?.originFileObj ?? null;
                      patchDraft({ uploadImageFile: file });
                      form.setFieldValue("uploadImageFile", file);
                    }}
                  >
                    <Button icon={<UploadIcon size={16} />}>
                      {t("mcpConfig.uploadImage.button.selectFile")}
                    </Button>
                  </Upload>
                </Form.Item>
              )}
              {(isContainer || isLocalImage) && (
                <Form.Item
                  label={t("mcpConfig.addContainer.port")}
                  htmlFor="add-mcp-port"
                  required
                >
                  <InputNumber
                    id="add-mcp-port"
                    placeholder={t("mcpConfig.addContainer.portPlaceholder")}
                    value={draft.containerPort}
                    onChange={(value) => {
                      const next = value ?? undefined;
                      patchDraft({ containerPort: next });
                      form.setFieldValue("containerPort", next);
                    }}
                    min={1}
                    max={65535}
                    className="!w-full"
                    controls={false}
                  />
                </Form.Item>
              )}
              {(isContainer || isApi) && (
                <Form.Item
                  label={t("mcpTools.addModal.jsonConfig")}
                  name={jsonField}
                  rules={isApi ? rules.openApiJson : rules.containerConfig}
                  extra={t(
                    isApi
                      ? "mcpConfig.openApiToMcp.form.apiJsonHint"
                      : "mcpConfig.addContainer.configHint"
                  )}
                >
                  <Input.TextArea
                    placeholder={t(
                      isApi
                        ? "mcpConfig.openApiToMcp.jsonPlaceholder"
                        : "mcpConfig.addContainer.configPlaceholder"
                    )}
                    {...bindField(jsonField)}
                    rows={4}
                  />
                </Form.Item>
              )}
              {(isRemote || isApi) && (
                <Form.Item
                  label={t("mcpTools.addModal.customHeaders")}
                  name="customHeaders"
                  rules={rules.customHeaders}
                >
                  <Input.TextArea
                    placeholder={t(
                      "mcpConfig.addServer.customHeadersPlaceholder"
                    )}
                    {...bindField("customHeaders")}
                    rows={4}
                  />
                </Form.Item>
              )}
              {(isRemote || isLocalImage) && (
                <Form.Item
                  label={t("mcpTools.addModal.bearerTokenOptional")}
                  name="authorizationToken"
                  rules={rules.authToken}
                >
                  <Input.Password
                    placeholder={t(
                      "mcpConfig.editServer.authorizationTokenPlaceholder"
                    )}
                    {...bindField("authorizationToken")}
                    autoComplete="new-password"
                  />
                </Form.Item>
              )}
              <McpTagField
                disabled={submitting}
                onEdit={() => setTagsOpen(true)}
              >
                {selectedTags.length > 0 ? (
                  <TagChips assignments={selectedTags} max={4} singleLine />
                ) : (
                  <span className="text-sm text-muted-foreground">—</span>
                )}
              </McpTagField>
            </div>
            {canSelectGroups && (
              <div hidden={!showGroupStep}>
                <Can permission="kb.groups:read">
                  <Form.Item
                    htmlFor="add-mcp-group-permission"
                    label={t("mcpTools.addModal.groupPermission")}
                  >
                    <Select
                      id="add-mcp-group-permission"
                      value={draft.ingroupPermission ?? "READ_ONLY"}
                      onChange={handlePermissionChange}
                      disabled={isApi}
                      options={[
                        {
                          value: "READ_ONLY",
                          label: t(
                            "knowledgeBase.ingroup.permission.READ_ONLY"
                          ),
                        },
                        {
                          value: "EDIT",
                          label: t("knowledgeBase.ingroup.permission.EDIT"),
                        },
                        {
                          value: "PRIVATE",
                          label: t("knowledgeBase.ingroup.permission.PRIVATE"),
                        },
                      ]}
                    />
                  </Form.Item>
                </Can>
                <Form.Item
                  label={t("tenantResources.groups.selectGroup")}
                  extra={
                    isApi
                      ? t("mcpTools.detail.groupPermissionUnsupported")
                      : undefined
                  }
                >
                  <McpGroupSelectionTable
                    groups={groups}
                    loading={loadingGroups}
                    selectedGroupIds={
                      isGroupSelectDisabled ? [] : (draft.groupIds ?? [])
                    }
                    disabled={isGroupSelectDisabled}
                    onChange={(groupIds) => patchDraft({ groupIds })}
                  />
                </Form.Item>
              </div>
            )}
          </Form>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-4">
          {isRemote && !showGroupStep && (
            <Button
              className="mr-auto"
              icon={<RefreshCw size={14} aria-hidden />}
              loading={testingConnection}
              disabled={!draft.serverUrl.trim() || submitting}
              onClick={handleTestConnection}
            >
              {t("mcpTools.editDetail.testConnection")}
            </Button>
          )}
          {deploymentStarted && (
            <Button className="mr-auto" onClick={() => setLogsOpen(true)}>
              {t("mcpTools.detail.viewContainerLogs")}
            </Button>
          )}
          <Button disabled={submitting} onClick={onClose}>
            {t("common.close")}
          </Button>
          {showGroupStep && (
            <Button disabled={submitting} onClick={() => setStep(0)}>
              {t("common.back")}
            </Button>
          )}
          <Button
            type="primary"
            autoInsertSpace={false}
            className="!h-8 !px-4 !py-[5px] !text-sm !leading-[22px] !shadow-none"
            onClick={
              canSelectGroups && !showGroupStep
                ? async () => {
                    if (await validateConfiguration()) setStep(1);
                  }
                : handleSubmit
            }
            loading={submitting}
            disabled={
              testingConnection || (isLocalImage && !draft.uploadImageFile)
            }
          >
            {t(
              canSelectGroups && !showGroupStep
                ? "mcpTools.addModal.next"
                : showGroupStep
                  ? "common.confirm"
                  : "mcpTools.addModal.saveAndAdd"
            )}
          </Button>
        </div>

        {deploymentStarted && (
          <McpContainerLogsModal
            open={logsOpen}
            onCancel={() => setLogsOpen(false)}
            containerId={deployedContainerId}
          />
        )}
        <ResourceTagAssignmentModal
          open={tagsOpen}
          onClose={() => setTagsOpen(false)}
          resourceType="mcp_service"
          resourceId=""
          definitions={tagDefinitions.data ?? []}
          definitionsLoading={tagLibraries.loading || tagDefinitions.loading}
          canEdit
          initialSelection={tagSelection}
          onConfirmSelection={setTagSelection}
        />
      </div>
    </ConfigProvider>
  );
}
