// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useState } from "react";
import { ArrowRight, RefreshCw, Trash2 } from "lucide-react";
import {
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
  McpTransportType,
  MCP_EDIT_SERVICE_DRAWER_WIDTH,
} from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";
import { resolveDeploymentType, toPrettyRegistryJson } from "@/lib/mcpTools";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import { useMcpServerList } from "@/hooks/mcp/useMcpServerList";
import { useMcpServiceDetail } from "@/hooks/mcpTools/useMcpServiceDetail";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { usePermission } from "@/hooks/permission/usePermission";
import { Can } from "@/components/permission/Can";
import ResourcePanelTitle from "@/components/resource/ResourcePanelTitle";
import panel from "@/components/resource/resource-panel.module.css";
import { Drawer } from "antd";
import McpHeaderFields from "./McpHeaderFields";
import RepositoryMcpIcon from "./shared/RepositoryMcpIcon";
import McpDeploymentCards from "./shared/McpDeploymentCards";
import McpGroupSelectionTable from "./shared/McpGroupSelectionTable";
import ResourceTagAssignmentModal from "@/components/tag/ResourceTagAssignmentModal";
import ResourceTagChips from "@/components/tag/ResourceTagChips";
import TagDefinitionManagementModal from "@/components/tag/TagDefinitionManagementModal";
import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";
import McpEditInspection from "./McpEditInspection";

interface McpServiceDetailModalProps {
  selectedService: McpServiceItem | null;
  onClose: () => void;
  onToggled?: (mcpId: number, next: McpServiceStatus) => void;
  onTagsChanged?: (mcpId: number) => void;
}

export default function McpServiceDetailModal({
  selectedService,
  onClose,
  onTagsChanged,
}: McpServiceDetailModalProps) {
  const { modal } = App.useApp();
  const { t } = useTranslation("common");
  const rules = useMcpFormRules();
  const [form] = Form.useForm();
  const formValues = Form.useWatch(
    (values) => ({
      name: values.name,
      description: values.description,
      serverUrl: values.serverUrl,
      authorizationToken: values.authorizationToken,
      customHeadersJson: JSON.stringify(values.customHeaders),
      openApiJson: values.openApiJson,
      containerConfigJson: values.containerConfigJson,
    }),
    { form, preserve: true }
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

  const { enableUploadImage } = useMcpServerList({
    enabled: Boolean(selectedService),
  });
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

  useEffect(() => {
    if (!selectedService) return;
    const draft = selectedService;
    form.setFieldsValue({
      name: draft.name,
      description: draft.description,
      version: draft.version,
      serverUrl: draft.serverUrl,
      authorizationToken: draft.authorizationToken ?? "",
      customHeaders: Object.entries(draft.customHeaders ?? {}).map(
        ([name, value]) => ({ name, value })
      ),
      openApiJson: toPrettyRegistryJson(draft.configJson),
      containerConfigJson: toPrettyRegistryJson(draft.configJson),
      containerPort: draft.containerPort,
      group_ids: draft.groupIds
        ? draft.groupIds.split(",").map(Number).filter(Boolean)
        : undefined,
      ingroup_permission: draft.ingroupPermission || "READ_ONLY",
    });
  }, [selectedService, form]);

  if (!selectedService || !draft) {
    return null;
  }

  const deploymentType = resolveDeploymentType(selectedService);
  const isRemoteLink = deploymentType === McpDeploymentType.REMOTE_LINK;
  const isContainer = deploymentType === McpDeploymentType.CONTAINER;
  const isApi = deploymentType === McpDeploymentType.API;
  const isLocalImage = deploymentType === McpDeploymentType.LOCAL_IMAGE;
  const isReadOnly = selectedService.permission === "READ_ONLY";
  const transport = selectedService.transportType;
  const remoteType =
    transport === McpTransportType.HTTP
      ? "streamable-http"
      : transport === McpTransportType.SSE
        ? "sse"
        : undefined;
  const headersChanged =
    formValues?.customHeadersJson !== undefined &&
    formValues.customHeadersJson !==
      JSON.stringify(
        Object.entries(selectedService.customHeaders ?? {}).map(
          ([name, value]) => ({ name, value })
        )
      );
  const connectionChanged =
    headersChanged ||
    (formValues?.serverUrl !== undefined &&
      formValues.serverUrl !== selectedService.serverUrl) ||
    (formValues?.authorizationToken !== undefined &&
      formValues.authorizationToken !==
        (selectedService.authorizationToken ?? "")) ||
    (isApi &&
      formValues?.openApiJson !== undefined &&
      formValues.openApiJson !==
        toPrettyRegistryJson(selectedService.configJson)) ||
    (isContainer &&
      formValues?.containerConfigJson !== undefined &&
      formValues.containerConfigJson !==
        toPrettyRegistryJson(selectedService.configJson));
  const previewName = formValues?.name ?? selectedService.name;
  const previewDescription =
    formValues?.description ?? selectedService.description;
  const previewUrl = formValues?.serverUrl ?? selectedService.serverUrl;
  const serverJson = isRemoteLink
    ? toPrettyRegistryJson({
        name: previewName,
        description: previewDescription,
        remotes: [
          {
            ...(remoteType && { type: remoteType }),
            url: previewUrl,
            headers: {},
          },
        ],
      })
    : draft.registryJson
      ? toPrettyRegistryJson(draft.registryJson)
      : undefined;

  const handleSave = async () => {
    if (isReadOnly) return;
    try {
      await form.validateFields();
    } catch {
      setStep(0);
      return;
    }

    const values = form.getFieldsValue();
    const parsedCustomHeaders =
      isRemoteLink || isApi
        ? Object.fromEntries(
            (
              (values.customHeaders ?? []) as Array<{
                name: string;
                value?: string;
              }>
            ).map(({ name, value }) => [name.trim(), value ?? ""])
          )
        : draft.customHeaders;

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
      version: draft.version,
      serverUrl: values.serverUrl ?? draft.serverUrl,
      authorizationToken: values.authorizationToken ?? draft.authorizationToken,
      customHeaders: parsedCustomHeaders,
      configJson: parsedConfigJson,
    };
    const ok = await detail.save(nextDraft);
    if (ok) onClose();
  };

  return (
    <>
      <ConfigProvider
        theme={{
          components: {
            Form: { itemMarginBottom: 16 },
          },
        }}
      >
        <Drawer
          open
          title={
            <ResourcePanelTitle
              title={selectedService.name}
              icon={<RepositoryMcpIcon deploymentType={deploymentType} />}
            />
          }
          closable={{ placement: "end", "aria-label": t("common.close") }}
          size={`min(${MCP_EDIT_SERVICE_DRAWER_WIDTH}px, 100vw)`}
          classNames={{
            body: "repository-detail-body mcp-edit-drawer-body !mb-4",
          }}
          onClose={onClose}
          footer={
            <div className={panel.footerActions}>
              {selectedService.permission === "EDIT" && (
                <Button
                  type="text"
                  danger
                  className="mr-auto"
                  icon={<Trash2 size={15} aria-hidden />}
                  loading={detail.deleting}
                  disabled={detail.saving}
                  onClick={() =>
                    modal.confirm({
                      centered: true,
                      title: t("mcpTools.mine.deleteConfirmTitle"),
                      content: t("mcpTools.mine.deleteConfirmDescription", {
                        name: selectedService.name,
                      }),
                      okText: t("common.delete"),
                      cancelText: t("common.cancel"),
                      okButtonProps: { danger: true },
                      onOk: detail.remove,
                    })
                  }
                >
                  {t("common.delete")}
                </Button>
              )}
              <Button className="min-w-[88px]" onClick={onClose}>
                {t("common.cancel")}
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
                disabled={isReadOnly || detail.deleting}
                icon={
                  canSelectGroups && !showGroupStep && !isReadOnly ? (
                    <ArrowRight size={15} aria-hidden />
                  ) : undefined
                }
                iconPlacement="end"
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
          <div className="flex w-full min-w-0 flex-col gap-4 bg-background">
            {canSelectGroups && (
              <Steps
                className="shrink-0 border-b border-border pb-3"
                current={showGroupStep ? 1 : 0}
                size="small"
                responsive={false}
                items={[
                  {
                    title: t("mcpTools.addModal.configureStep"),
                    content: t("mcpTools.editDetail.configureStepDescription"),
                  },
                  {
                    title: t("mcpTools.editDetail.accessStep"),
                    content: t("mcpTools.editDetail.accessStepDescription"),
                  },
                ]}
              />
            )}
            <Form
              form={form}
              layout="vertical"
              colon={false}
              className={`${panel.editForm} space-y-4`}
            >
              <div className={showGroupStep ? "hidden" : "flex flex-col gap-4"}>
                <section
                  className={`${panel.editSection} flex flex-col gap-4`}
                  aria-labelledby="mcp-edit-basic"
                >
                  <h3 id="mcp-edit-basic" className="text-body-2 font-semibold">
                    {t("mcpTools.editDetail.basic")}
                  </h3>
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
                  <Form.Item
                    name="description"
                    label={t("common.description")}
                    rules={rules.description}
                    extra={t("mcpTools.editDetail.descriptionHint")}
                    className="!mb-0"
                  >
                    <Input.TextArea
                      rows={4}
                      placeholder={t("mcpTools.detail.serviceDescription")}
                      disabled={isReadOnly}
                    />
                  </Form.Item>
                  <Form.Item
                    label={t("mcpTools.detail.tags")}
                    className="!mb-0"
                  >
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
                </section>
                <section
                  className={`${panel.editSection} flex flex-col gap-4`}
                  aria-labelledby="mcp-edit-connection"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3
                      id="mcp-edit-connection"
                      className="text-body-2 font-semibold"
                    >
                      {t("mcpTools.editDetail.connection")}
                    </h3>
                    <Button
                      size="small"
                      icon={<RefreshCw size={14} aria-hidden />}
                      loading={detail.healthChecking}
                      disabled={
                        connectionChanged ||
                        detail.saving ||
                        detail.loadingTools ||
                        isReadOnly
                      }
                      onClick={async () => {
                        if (connectionChanged || isReadOnly) return;
                        if (await detail.runHealthCheck())
                          await detail.refreshTools();
                      }}
                    >
                      {t("mcpTools.editDetail.testConnection")}
                    </Button>
                  </div>
                  {connectionChanged && (
                    <p className="text-xs text-muted-foreground">
                      {t("mcpTools.editDetail.saveBeforeTest")}
                    </p>
                  )}
                  <McpDeploymentCards
                    ariaLabel={t("mcpTools.detail.addMethod")}
                    value={deploymentType}
                    includeLocalImage={enableUploadImage}
                  />
                  {(isRemoteLink || isApi) && (
                    <div className="grid items-start gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(9rem,0.4fr)]">
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
                          autoComplete="off"
                          disabled={isReadOnly}
                        />
                      </Form.Item>
                      {isRemoteLink && (
                        <Form.Item
                          label={t("mcpTools.editDetail.protocol")}
                          className="!mb-0"
                        >
                          <Input
                            readOnly
                            aria-label={t("mcpTools.editDetail.protocol")}
                            value={
                              remoteType === "streamable-http"
                                ? "Streamable HTTP"
                                : remoteType === "sse"
                                  ? "SSE"
                                  : t("mcpTools.editDetail.protocolAuto")
                            }
                          />
                        </Form.Item>
                      )}
                    </div>
                  )}
                  {(isRemoteLink || isLocalImage) && (
                    <Form.Item
                      name="authorizationToken"
                      label={t("mcpConfig.editServer.authorizationToken")}
                      rules={rules.authToken}
                      extra={t("mcpTools.editDetail.tokenHint")}
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
                  {(isRemoteLink || isApi) && (
                    <McpHeaderFields readOnly={isReadOnly} />
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
                        placeholder={t(
                          "mcpConfig.openApiToMcp.jsonPlaceholder"
                        )}
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
                        value={draft.containerPort}
                        min={1}
                        max={65535}
                        className="!w-full"
                        controls={false}
                        disabled
                      />
                    </Form.Item>
                  )}
                </section>
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
                onLoadTools={detail.loadTools}
                serverJson={serverJson}
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
    </>
  );
}
