// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  ConfigProvider,
  Form,
  Input,
  InputNumber,
  Select,
  Steps,
} from "antd";
import { useTranslation } from "react-i18next";
import {
  McpDeploymentType,
  McpServiceStatus,
  MCP_EDIT_SERVICE_DRAWER_WIDTH,
} from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";
import { resolveDeploymentType, toPrettyRegistryJson } from "@/lib/mcpTools";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import { useMcpServiceDetail } from "@/hooks/mcpTools/useMcpServiceDetail";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { usePermission } from "@/hooks/permission/usePermission";
import { Can } from "@/components/permission/Can";
import { Drawer } from "antd";
import ContainerPortField from "./shared/ContainerPortField";
import McpGroupSelectionTable from "./shared/McpGroupSelectionTable";
import ResourceTagAssignmentModal from "@/components/tag/ResourceTagAssignmentModal";
import ResourceTagChips from "@/components/tag/ResourceTagChips";
import TagDefinitionManagementModal from "@/components/tag/TagDefinitionManagementModal";
import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";
import McpEditInspection from "./McpEditInspection";
import PublishConfirmModal from "./PublishConfirmModal";

interface McpServiceDetailModalProps {
  selectedService: McpServiceItem | null;
  onClose: () => void;
  onToggled?: (mcpId: number, next: McpServiceStatus) => void;
  onTagsChanged?: (mcpId: number) => void;
}

const DEPLOYMENT_OPTIONS = [
  {
    value: McpDeploymentType.REMOTE_LINK,
    descriptionKey: "mcpTools.addModal.mode.remoteDescription",
    labelKey: "mcpConfig.addServer.title",
  },
  {
    value: McpDeploymentType.CONTAINER,
    descriptionKey: "mcpTools.addModal.mode.containerDescription",
    labelKey: "mcpTools.addModal.mode.container",
  },
  {
    value: McpDeploymentType.API,
    descriptionKey: "mcpTools.addModal.mode.apiDescription",
    labelKey: "mcpTools.addModal.mode.api",
  },
  {
    value: McpDeploymentType.LOCAL_IMAGE,
    descriptionKey: "mcpTools.addModal.mode.uploadDescription",
    labelKey: "mcpConfig.uploadImage.title",
  },
] as const;

export default function McpServiceDetailModal({
  selectedService,
  onClose,
  onTagsChanged,
}: McpServiceDetailModalProps) {
  const { modal } = App.useApp();
  const { t } = useTranslation("common");
  const rules = useMcpFormRules();
  const [form] = Form.useForm();
  const [publishConfirmOpen, setPublishConfirmOpen] = useState(false);
  const [deploymentType, setDeploymentType] = useState<McpDeploymentType>(
    McpDeploymentType.REMOTE_LINK
  );
  const [assignOpen, setAssignOpen] = useState(false);
  const [tagPreviewRefreshKey, setTagPreviewRefreshKey] = useState(0);
  const [tagManagementOpen, setTagManagementOpen] = useState(false);
  const { data: tagLibraries } = useTagLibraries();
  const defaultLibrary =
    tagLibraries?.find(
      (library) => library.bucket_key === "default_resource"
    ) ?? null;
  const { data: assignDefinitions, refresh: refreshAssignDefinitions } =
    useTagDefinitions(defaultLibrary?.bucket_id ?? null);
  const [containerPort, setContainerPort] = useState<number | undefined>();

  const detail = useMcpServiceDetail({ selectedService, onClose });
  const { user } = useAuthorizationContext();
  const { isReady, can } = usePermission();
  const canSelectGroups = isReady && can("group:read");
  const [step, setStep] = useState(0);
  const showGroupStep = canSelectGroups && step === 1;
  const tenantId = user?.tenantId || null;
  const { data: groupData, isLoading: loadingGroups } = useGroupList(tenantId);
  const groups = groupData?.groups || [];
  const { draft, setDraft } = detail;

  const originalDeploymentType = useMemo(
    () =>
      draft
        ? resolveDeploymentType({
            transportType: draft.transportType,
            deploymentType: draft.deploymentType,
            configJson: draft.configJson,
            serverUrl: draft.serverUrl,
            source: draft.source,
          })
        : McpDeploymentType.REMOTE_LINK,
    [draft]
  );

  useEffect(() => {
    if (!draft) return;
    const nextDeploymentType = resolveDeploymentType({
      transportType: draft.transportType,
      deploymentType: draft.deploymentType,
      configJson: draft.configJson,
      serverUrl: draft.serverUrl,
      source: draft.source,
    });
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Preserve the existing modal reset when its external open state changes.
    setDeploymentType(nextDeploymentType);
    setContainerPort(draft.containerPort);
    form.setFieldsValue({
      name: draft.name,
      description: draft.description,
      version: draft.version,
      serverUrl: draft.serverUrl,
      authorizationToken: draft.authorizationToken ?? "",
      customHeaders: draft.customHeaders
        ? JSON.stringify(draft.customHeaders, null, 2)
        : "",
      openApiJson: toPrettyRegistryJson(draft.configJson),
      containerConfigJson: toPrettyRegistryJson(draft.configJson),
      containerPort: draft.containerPort,
      group_ids: draft.groupIds
        ? draft.groupIds.split(",").map(Number).filter(Boolean)
        : undefined,
      ingroup_permission: draft.ingroupPermission || "READ_ONLY",
    });
  }, [draft, form]);

  if (!selectedService || !draft) {
    return null;
  }

  const isRemoteLink = deploymentType === McpDeploymentType.REMOTE_LINK;
  const isContainer = deploymentType === McpDeploymentType.CONTAINER;
  const isApi = deploymentType === McpDeploymentType.API;
  const isLocalImage = deploymentType === McpDeploymentType.LOCAL_IMAGE;
  const isUnsupported = deploymentType !== originalDeploymentType;
  const isReadOnly = selectedService?.permission === "READ_ONLY";

  const handleSave = async () => {
    if (isUnsupported || isReadOnly) return;
    try {
      await form.validateFields();
    } catch {
      setStep(0);
      return;
    }

    const values = form.getFieldsValue();
    let parsedCustomHeaders: Record<string, string> | undefined;
    if (values.customHeaders?.trim()) {
      try {
        parsedCustomHeaders = JSON.parse(values.customHeaders.trim());
      } catch {
        setStep(0);
        modal.error({
          content: t("mcpConfig.message.invalidCustomHeadersJson"),
        });
        return;
      }
    }

    let parsedConfigJson = draft.configJson;
    if (isApi) {
      try {
        parsedConfigJson = JSON.parse(String(values.openApiJson || "").trim());
      } catch {
        setStep(0);
        modal.error({
          content: t("mcpConfig.openApiToMcp.message.invalidJson"),
        });
        return;
      }
    }
    if (isContainer) {
      try {
        parsedConfigJson = JSON.parse(
          String(values.containerConfigJson || "").trim()
        );
      } catch {
        setStep(0);
        modal.error({
          content: t("mcpTools.add.error.containerJsonInvalid"),
        });
        return;
      }
    }

    const nextDraft = {
      ...draft,
      name: values.name ?? "",
      description: values.description ?? "",
      version: values.version ?? "",
      serverUrl: values.serverUrl ?? "",
      authorizationToken: values.authorizationToken ?? "",
      customHeaders: parsedCustomHeaders,
      configJson: parsedConfigJson,
    };
    detail.setDraft(nextDraft);
    const ok = await detail.save(nextDraft);
    if (ok) onClose();
  };

  return (
    <>
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
        <Drawer
          open
          title={t("common.edit")}
          width={`min(${MCP_EDIT_SERVICE_DRAWER_WIDTH}px, 100vw)`}
          classNames={{
            body: "repository-detail-body mcp-edit-drawer-body !mb-4",
          }}
          onClose={onClose}
          footer={
            <div className="flex justify-end gap-4">
              <Button className="min-w-[88px]" onClick={onClose}>
                {t("common.close")}
              </Button>
              {showGroupStep && (
                <Button className="min-w-[88px]" onClick={() => setStep(0)}>
                  {t("common.back")}
                </Button>
              )}
              <Button
                type="primary"
                className="min-w-[88px]"
                loading={detail.saving}
                disabled={isUnsupported || isReadOnly}
                onClick={async () => {
                  if (!canSelectGroups || showGroupStep) {
                    await handleSave();
                    return;
                  }
                  try {
                    await form.validateFields();
                    setStep(1);
                  } catch {
                    // Ant Design displays the configuration field errors.
                  }
                }}
              >
                {t(
                  isReadOnly
                    ? "mcpTools.detail.noEditPermission"
                    : canSelectGroups && !showGroupStep
                      ? "mcpTools.addModal.next"
                      : "mcpTools.detail.save"
                )}
              </Button>
            </div>
          }
        >
          <div className="w-full min-w-0 space-y-4 bg-white">
            {canSelectGroups && (
              <Steps
                className="relative shrink-0 !justify-between before:absolute before:inset-x-10 before:top-3 before:h-px before:bg-[#0067D1]"
                classNames={{
                  item: "!flex-none",
                  itemRail: "!hidden",
                  itemWrapper: "relative !gap-2",
                  itemTitle: "!text-sm",
                }}
                current={showGroupStep ? 1 : 0}
                size="small"
                titlePlacement="vertical"
                responsive={false}
                items={[
                  { title: t("mcpTools.addModal.configureStep") },
                  { title: t("mcpTools.addModal.groupsStep") },
                ]}
              />
            )}
            <Form
              form={form}
              layout="vertical"
              colon={false}
              className="space-y-4 text-sm text-[#191919]"
            >
              <div hidden={showGroupStep} className="space-y-4">
                <div
                  role="list"
                  aria-label={t("mcpTools.detail.addMethod")}
                  className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,155px),1fr))] gap-4"
                >
                  {DEPLOYMENT_OPTIONS.map(
                    ({ value, labelKey, descriptionKey }) => (
                      <div
                        key={value}
                        role="listitem"
                        aria-current={
                          value === originalDeploymentType ? "true" : undefined
                        }
                        className={`min-h-[104px] rounded-lg border bg-white p-4 ${value === originalDeploymentType ? "border-[#0067D1]" : "border-[#C9C9C9]"}`}
                      >
                        <div className="text-sm leading-5 font-medium text-[#191919]">
                          {t(labelKey)}
                        </div>
                        <div className="mt-1 text-sm leading-5 text-[#777777]">
                          {t(descriptionKey)}
                        </div>
                      </div>
                    )
                  )}
                </div>

                {isUnsupported ? (
                  <Alert
                    type="info"
                    showIcon
                    title={t("mcpTools.addModal.unsupportedTitle")}
                    description={t(
                      "mcpTools.detail.deploymentChangeUnsupported"
                    )}
                  />
                ) : null}

                <Form.Item
                  name="name"
                  label={t("mcpTools.addModal.name")}
                  rules={rules.name}
                  className="!mb-0"
                >
                  <Input
                    placeholder={t(
                      isLocalImage
                        ? "mcpConfig.uploadImage.serviceNamePlaceholder"
                        : "mcpConfig.editServer.serviceNamePlaceholder"
                    )}
                    maxLength={isLocalImage ? undefined : 20}
                    autoComplete={isRemoteLink ? "off" : undefined}
                    disabled={isReadOnly}
                  />
                </Form.Item>
                <Form.Item label={t("mcpTools.detail.tags")} className="!mb-0">
                  <div className="flex min-h-8 min-w-0 items-center gap-2 rounded border border-[#C9C9C9] px-3">
                    <div className="min-w-0 flex-1 overflow-hidden whitespace-nowrap">
                      <ResourceTagChips
                        resourceType="mcp_service"
                        resourceId={String(selectedService.mcpId)}
                        max={4}
                        refreshKey={tagPreviewRefreshKey}
                        singleLine
                        emptyText={
                          <span className="text-sm text-slate-400">—</span>
                        }
                      />
                    </div>
                    <Button
                      type="link"
                      size="small"
                      disabled={isReadOnly}
                      onClick={() => setAssignOpen(true)}
                    >
                      {t("tagManagement.action.editTags")}
                    </Button>
                  </div>
                </Form.Item>
                <Form.Item
                  name="description"
                  label={t("common.description")}
                  rules={rules.description}
                  className="!mb-0"
                >
                  <Input.TextArea
                    rows={4}
                    placeholder={t("mcpTools.detail.serviceDescription")}
                    disabled={isReadOnly}
                  />
                </Form.Item>
                {(isRemoteLink || isApi) && (
                  <>
                    <Form.Item
                      name="serverUrl"
                      label={t("mcpTools.detail.serverUrl")}
                      rules={rules.httpUrl}
                      className="!mb-0"
                    >
                      <Input
                        placeholder={t(
                          isApi
                            ? "mcpConfig.openapiService.form.serverUrlPlaceholder"
                            : "mcpConfig.addServer.urlPlaceholder"
                        )}
                        autoComplete={isRemoteLink ? "off" : undefined}
                        disabled={isReadOnly}
                      />
                    </Form.Item>
                    <Form.Item
                      name="customHeaders"
                      label={t("mcpConfig.addServer.customHeaders")}
                      className="!mb-0"
                    >
                      <Input.TextArea
                        rows={4}
                        placeholder={t(
                          "mcpConfig.addServer.customHeadersPlaceholder"
                        )}
                        disabled={isReadOnly}
                      />
                    </Form.Item>
                  </>
                )}
                {(isRemoteLink || isLocalImage) && (
                  <Form.Item
                    name="authorizationToken"
                    label={t("mcpConfig.editServer.authorizationToken")}
                    rules={rules.authToken}
                    className="!mb-0"
                  >
                    <Input.Password
                      placeholder={t(
                        "mcpConfig.editServer.authorizationTokenPlaceholder"
                      )}
                      autoComplete="new-password"
                      disabled={isReadOnly}
                    />
                  </Form.Item>
                )}
                {isApi && (
                  <Form.Item
                    name="openApiJson"
                    label={t("mcpConfig.openapiService.form.openapiJson")}
                    rules={rules.openApiJson}
                    extra={t("mcpConfig.openApiToMcp.form.apiJsonHint")}
                    className="!mb-0"
                  >
                    <Input.TextArea
                      rows={6}
                      placeholder={t("mcpConfig.openApiToMcp.jsonPlaceholder")}
                      disabled={isReadOnly}
                    />
                  </Form.Item>
                )}
                {isContainer && (
                  <Form.Item
                    name="containerConfigJson"
                    label={t("mcpTools.detail.containerConfig")}
                    rules={rules.containerConfig}
                    extra={t("mcpConfig.addContainer.configHint")}
                    className="!mb-0"
                  >
                    <Input.TextArea
                      rows={6}
                      className="font-mono"
                      placeholder={t(
                        "mcpConfig.addContainer.configPlaceholder"
                      )}
                      disabled={isReadOnly}
                    />
                  </Form.Item>
                )}
                {(isContainer || isLocalImage) && (
                  <Form.Item
                    label={t("mcpConfig.addContainer.port")}
                    extra={
                      isLocalImage
                        ? t("mcpConfig.uploadImage.fileHint")
                        : undefined
                    }
                    className="!mb-0"
                  >
                    <InputNumber
                      value={containerPort}
                      min={1}
                      max={65535}
                      className="!w-full"
                      controls={false}
                      disabled
                    />
                  </Form.Item>
                )}

                <div hidden>
                  <div className="space-y-2">
                    <Form.Item name="name" rules={rules.name} className="mb-0">
                      <Input
                        className="w-full rounded-md"
                        placeholder={t("mcpTools.detail.serviceName")}
                        disabled={isReadOnly}
                      />
                    </Form.Item>
                    <Form.Item
                      name="description"
                      rules={rules.description}
                      className="mb-0"
                    >
                      <Input
                        className="w-full rounded-md"
                        placeholder={t("mcpTools.detail.serviceDescription")}
                        disabled={isReadOnly}
                      />
                    </Form.Item>
                  </div>

                  {isRemoteLink ? (
                    <div>
                      <label className="mb-1 block text-sm font-medium text-slate-700">
                        {t("mcpTools.detail.serviceConfigTitle")}
                      </label>
                      <div className="space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
                        <div>
                          <label className="mb-1 block text-sm font-normal text-slate-500">
                            {t("mcpTools.addModal.serverUrl")}
                          </label>
                          <div className="flex items-center gap-2">
                            <Form.Item
                              name="serverUrl"
                              rules={rules.httpUrl}
                              className="mb-0 flex-1"
                            >
                              <Input
                                className="w-full rounded-md"
                                placeholder={t("mcpTools.addModal.serverUrl")}
                                disabled={isReadOnly}
                              />
                            </Form.Item>
                            <label className="flex shrink-0 items-center gap-1 text-xs text-slate-400">
                              <input
                                type="checkbox"
                                className="rounded border-slate-300"
                                checked={
                                  draft.sharedFields?.["serverUrl"] ?? false
                                }
                                disabled={isReadOnly}
                                onChange={(e) => {
                                  const next = {
                                    ...(draft.sharedFields || {}),
                                    serverUrl: e.target.checked,
                                  };
                                  setDraft((prev) =>
                                    prev
                                      ? { ...prev, sharedFields: next }
                                      : prev
                                  );
                                }}
                              />
                              {t("mcpTools.detail.share")}
                            </label>
                          </div>
                        </div>

                        <div>
                          <label className="mb-1 block text-sm font-normal text-slate-500">
                            {t("mcpTools.addModal.bearerTokenOptional")}
                          </label>
                          <div className="flex items-center gap-2">
                            <Form.Item
                              name="authorizationToken"
                              rules={rules.authToken}
                              className="mb-0 flex-1"
                            >
                              <Input
                                className="w-full rounded-md"
                                placeholder={t(
                                  "mcpTools.addModal.bearerTokenPlaceholder"
                                )}
                                disabled={isReadOnly}
                              />
                            </Form.Item>
                            <label className="flex shrink-0 items-center gap-1 text-xs text-slate-400">
                              <input
                                type="checkbox"
                                className="rounded border-slate-300"
                                checked={
                                  draft.sharedFields?.["authorizationToken"] ??
                                  false
                                }
                                disabled={isReadOnly}
                                onChange={(e) => {
                                  const next = {
                                    ...(draft.sharedFields || {}),
                                    authorizationToken: e.target.checked,
                                  };
                                  setDraft((prev) =>
                                    prev
                                      ? { ...prev, sharedFields: next }
                                      : prev
                                  );
                                }}
                              />
                              {t("mcpTools.detail.share")}
                            </label>
                          </div>
                        </div>

                        <div>
                          <label className="mb-1 block text-sm font-normal text-slate-500">
                            {t("mcpTools.addModal.customHeaders")}
                          </label>
                          <div className="flex items-center gap-2">
                            <Form.Item
                              name="customHeaders"
                              className="mb-0 flex-1"
                            >
                              <Input.TextArea
                                rows={2}
                                className="w-full rounded-md"
                                placeholder={t(
                                  "mcpTools.addModal.customHeadersPlaceholder"
                                )}
                                disabled={isReadOnly}
                              />
                            </Form.Item>
                            <label className="flex shrink-0 items-center gap-1 self-start pt-1 text-xs text-slate-400">
                              <input
                                type="checkbox"
                                className="rounded border-slate-300"
                                checked={
                                  draft.sharedFields?.["customHeaders"] ?? false
                                }
                                disabled={isReadOnly}
                                onChange={(e) => {
                                  const next = {
                                    ...(draft.sharedFields || {}),
                                    customHeaders: e.target.checked,
                                  };
                                  setDraft((prev) =>
                                    prev
                                      ? { ...prev, sharedFields: next }
                                      : prev
                                  );
                                }}
                              />
                              {t("mcpTools.detail.share")}
                            </label>
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : null}

                  {isApi ? (
                    <div>
                      <label className="mb-1 block text-sm font-medium text-slate-700">
                        {t("mcpTools.detail.serviceConfigTitle")}
                      </label>
                      <div className="space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
                        <div>
                          <label className="mb-1 block text-sm font-normal text-slate-500">
                            {t("mcpConfig.openapiService.form.serverUrl")}
                          </label>
                          <Form.Item
                            name="serverUrl"
                            rules={rules.httpUrl}
                            className="mb-0"
                          >
                            <Input
                              className="w-full rounded-md"
                              placeholder={t(
                                "mcpConfig.openapiService.form.serverUrlPlaceholder"
                              )}
                              disabled={isReadOnly}
                            />
                          </Form.Item>
                        </div>

                        <div>
                          <label className="mb-1 block text-sm font-normal text-slate-500">
                            {t("mcpConfig.addServer.customHeaders")}
                          </label>
                          <Form.Item name="customHeaders" className="mb-0">
                            <Input.TextArea
                              rows={2}
                              className="w-full rounded-md"
                              placeholder={t(
                                "mcpConfig.addServer.customHeadersPlaceholder"
                              )}
                              disabled={isReadOnly}
                            />
                          </Form.Item>
                        </div>

                        <div>
                          <label className="mb-1 block text-sm font-normal text-slate-500">
                            {t("mcpConfig.openapiService.form.openapiJson")}
                          </label>
                          <Form.Item name="openApiJson" className="mb-0">
                            <Input.TextArea
                              rows={6}
                              className="w-full rounded-md"
                              placeholder={t(
                                "mcpConfig.openApiToMcp.jsonPlaceholder"
                              )}
                              disabled={isReadOnly}
                            />
                          </Form.Item>
                        </div>
                      </div>
                    </div>
                  ) : null}

                  {isContainer ? (
                    <div>
                      <label className="mb-1 block text-sm font-medium text-slate-700">
                        {t("mcpTools.detail.serviceConfigTitle")}
                      </label>
                      <div className="space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
                        <div>
                          <label className="mb-1 block text-sm font-normal text-slate-500">
                            {t("mcpTools.addModal.containerConfig")}
                          </label>
                          <div className="flex items-center gap-2">
                            <Form.Item
                              name="containerConfigJson"
                              className="mb-0 flex-1"
                            >
                              <Input.TextArea
                                rows={5}
                                className="w-full rounded-md bg-white text-slate-600"
                                placeholder={t(
                                  "mcpTools.addModal.containerConfigPlaceholder"
                                )}
                                disabled={isReadOnly}
                              />
                            </Form.Item>
                            <label className="flex shrink-0 items-center gap-1 self-start pt-1 text-xs text-slate-400">
                              <input
                                type="checkbox"
                                className="rounded border-slate-300"
                                checked={
                                  draft.sharedFields?.["containerConfigJson"] ??
                                  false
                                }
                                disabled={isReadOnly}
                                onChange={(e) => {
                                  const next = {
                                    ...(draft.sharedFields || {}),
                                    containerConfigJson: e.target.checked,
                                  };
                                  setDraft((prev) =>
                                    prev
                                      ? { ...prev, sharedFields: next }
                                      : prev
                                  );
                                }}
                              />
                              {t("mcpTools.detail.share")}
                            </label>
                          </div>
                        </div>

                        <Form.Item name="containerPort" className="mb-0">
                          <ContainerPortField
                            scope="detail"
                            enabled={false}
                            containerPort={containerPort}
                            setContainerPort={(value) => {
                              setContainerPort(value);
                              form.setFieldValue("containerPort", value);
                            }}
                          />
                        </Form.Item>
                      </div>
                    </div>
                  ) : null}

                  {isLocalImage ? (
                    <div>
                      <label className="mb-1 block text-sm font-medium text-slate-700">
                        {t("mcpTools.detail.serviceConfigTitle")}
                      </label>
                      <div className="space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
                        <Form.Item name="containerPort" className="mb-0">
                          <ContainerPortField
                            scope="detail"
                            enabled={false}
                            containerPort={containerPort}
                            setContainerPort={(value) => {
                              setContainerPort(value);
                              form.setFieldValue("containerPort", value);
                            }}
                          />
                        </Form.Item>
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>
              {canSelectGroups && (
                <div hidden={!showGroupStep}>
                  <Can permission="kb.groups:read">
                    <Form.Item
                      name="ingroup_permission"
                      label={t("mcpTools.addModal.groupPermission")}
                    >
                      <Select
                        value={draft.ingroupPermission ?? "READ_ONLY"}
                        disabled={isReadOnly || isApi}
                        onChange={(value) => {
                          setDraft((prev) =>
                            prev
                              ? {
                                  ...prev,
                                  ingroupPermission: value as
                                    "EDIT" | "READ_ONLY" | "PRIVATE",
                                }
                              : prev
                          );
                          form.setFieldValue("ingroup_permission", value);
                        }}
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
                            label: t(
                              "knowledgeBase.ingroup.permission.PRIVATE"
                            ),
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
                        draft.groupIds
                          ? draft.groupIds
                              .split(",")
                              .map(Number)
                              .filter(Boolean)
                          : []
                      }
                      disabled={isReadOnly || isApi}
                      onChange={(values) => {
                        setDraft((prev) =>
                          prev ? { ...prev, groupIds: values.join(",") } : prev
                        );
                        form.setFieldValue("group_ids", values);
                      }}
                    />
                  </Form.Item>
                </div>
              )}
            </Form>

            <div hidden={showGroupStep}>
              <McpEditInspection
                name={draft.name}
                tools={detail.toolsState.tools}
                loadingTools={detail.loadingTools}
                onLoadTools={detail.refreshTools}
                serverJson={
                  draft.registryJson
                    ? toPrettyRegistryJson(draft.registryJson)
                    : undefined
                }
                containerConfig={
                  draft.configJson
                    ? toPrettyRegistryJson(draft.configJson)
                    : undefined
                }
                showLogs={isContainer || isLocalImage}
                containerId={draft.containerId}
                active={!showGroupStep}
              />
            </div>
          </div>
        </Drawer>
      </ConfigProvider>

      <ResourceTagAssignmentModal
        open={assignOpen}
        onClose={() => {
          setAssignOpen(false);
          setTagPreviewRefreshKey((current) => current + 1);
          if (selectedService) {
            onTagsChanged?.(selectedService.mcpId);
          }
        }}
        resourceType="mcp_service"
        resourceId={String(selectedService.mcpId)}
        definitions={assignDefinitions ?? []}
        canEdit={!isReadOnly}
        onManageDefinitions={() => setTagManagementOpen(true)}
      />

      <TagDefinitionManagementModal
        open={tagManagementOpen}
        onClose={() => {
          setTagManagementOpen(false);
          void refreshAssignDefinitions();
        }}
        bucketId={defaultLibrary?.bucket_id ?? 0}
        bucketName={defaultLibrary?.bucket_name ?? ""}
        canManage={!isReadOnly}
      />

      <PublishConfirmModal
        open={publishConfirmOpen}
        source={selectedService}
        publishing={detail.publishing}
        tenantId={tenantId}
        onCancel={() => setPublishConfirmOpen(false)}
        onConfirm={async (override) => {
          const ok = await detail.publish(override);
          if (ok) setPublishConfirmOpen(false);
        }}
      />
    </>
  );
}
