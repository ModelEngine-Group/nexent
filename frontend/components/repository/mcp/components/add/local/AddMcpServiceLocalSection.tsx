// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useState } from "react";
import {
  Button,
  ConfigProvider,
  Form,
  Input,
  InputNumber,
  Select,
  Radio,
  Steps,
  Upload,
} from "antd";
import type { UploadFile } from "antd";
import { Upload as UploadIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { McpDeploymentType, McpTransportType } from "@/const/mcpTools";
import type { LocalAddMcpDraft } from "@/types/mcpTools";
import { useMcpAddLocal } from "@/hooks/mcpTools/useMcpAddLocal";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { StandardButton } from "@/components/common/StandardButton";
import McpGroupSelectionTable from "../../shared/McpGroupSelectionTable";
import { usePermission } from "@/hooks/permission/usePermission";
import { Can } from "@/components/permission/Can";
import McpContainerLogsModal from "@/components/mcp/McpContainerLogsModal";

/** Maps the creation options to deployment types. */
const DEPLOYMENT_TAB_ITEMS = [
  {
    key: "remote",
    type: McpDeploymentType.REMOTE_LINK,
    labelKey: "mcpConfig.addServer.title",
    descriptionKey: "mcpTools.addModal.mode.remoteDescription",
  },
  {
    key: "container",
    type: McpDeploymentType.CONTAINER,
    labelKey: "mcpTools.addModal.mode.container",
    descriptionKey: "mcpTools.addModal.mode.containerDescription",
  },
  {
    key: "openapi",
    type: McpDeploymentType.API,
    labelKey: "mcpTools.addModal.mode.api",
    descriptionKey: "mcpTools.addModal.mode.apiDescription",
  },
  {
    key: "upload",
    type: McpDeploymentType.LOCAL_IMAGE,
    labelKey: "mcpConfig.uploadImage.title",
    descriptionKey: "mcpTools.addModal.mode.uploadDescription",
  },
] as const;

const DEPLOYMENT_TAB_KEY: Record<McpDeploymentType, string> = {
  [McpDeploymentType.REMOTE_LINK]: "remote",
  [McpDeploymentType.CONTAINER]: "container",
  [McpDeploymentType.API]: "openapi",
  [McpDeploymentType.LOCAL_IMAGE]: "upload",
};

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

  const deploymentTabItems = enableUploadImage
    ? DEPLOYMENT_TAB_ITEMS
    : DEPLOYMENT_TAB_ITEMS.filter(
        (item) => item.type !== McpDeploymentType.LOCAL_IMAGE
      );
  const activeTabKey = DEPLOYMENT_TAB_KEY[deploymentType];

  const handleTabChange = (key: string) => {
    const item = DEPLOYMENT_TAB_ITEMS.find((i) => i.key === key);
    if (!item) return;
    const nextType = item.type;
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
    await submit(draft);
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
        {canSelectGroups && (
          <Steps
            className="relative shrink-0 !justify-between before:absolute before:inset-x-10 before:top-3 before:h-px before:bg-[#0067D1]"
            classNames={{
              item: "!flex-none",
              itemRail: "!hidden",
              itemWrapper: "relative !gap-2",
              itemTitle: "!text-sm",
            }}
            current={step}
            size="small"
            titlePlacement="vertical"
            responsive={false}
            items={[
              { title: t("mcpTools.addModal.configureStep") },
              { title: t("mcpTools.addModal.groupsStep") },
            ]}
          />
        )}
        <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-width:thin]">
          <Form form={form} layout="vertical" colon={false}>
            <div hidden={showGroupStep}>
              <Radio.Group
                aria-label={t("mcpTools.addModal.configureStep")}
                value={activeTabKey}
                onChange={(event) => handleTabChange(event.target.value)}
                className="!mb-4 !grid w-full grid-cols-[repeat(auto-fit,minmax(min(100%,155px),1fr))] gap-4"
              >
                {deploymentTabItems.map(({ key, labelKey, descriptionKey }) => (
                  <Radio.Button
                    key={key}
                    value={key}
                    className="!h-auto min-h-[104px] !whitespace-normal !rounded-lg !border !px-4 !py-4 !leading-5 before:!hidden"
                  >
                    <span className="block font-medium text-[#191919]">
                      {t(labelKey)}
                    </span>
                    <span className="mt-1 block font-normal text-[#777777]">
                      {t(descriptionKey)}
                    </span>
                  </Radio.Button>
                ))}
              </Radio.Group>
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
          {deploymentStarted && (
            <StandardButton
              className="mr-auto"
              onClick={() => setLogsOpen(true)}
            >
              {t("mcpTools.detail.viewContainerLogs")}
            </StandardButton>
          )}
          <StandardButton disabled={submitting} onClick={onClose}>
            {t("common.close")}
          </StandardButton>
          {showGroupStep && (
            <StandardButton disabled={submitting} onClick={() => setStep(0)}>
              {t("common.back")}
            </StandardButton>
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
            disabled={isLocalImage && !draft.uploadImageFile}
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
      </div>
    </ConfigProvider>
  );
}
