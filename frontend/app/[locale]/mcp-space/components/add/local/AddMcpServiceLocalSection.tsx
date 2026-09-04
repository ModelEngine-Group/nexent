import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Tabs,
  Upload,
} from "antd";
import type { UploadFile } from "antd";
import { Container, Import, Unplug, Upload as UploadIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { McpDeploymentType, McpTransportType } from "@/const/mcpTools";
import type { LocalAddMcpDraft } from "@/types/mcpTools";
import { useMcpAddLocal } from "@/hooks/mcpTools/useMcpAddLocal";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { Can } from "@/components/permission/Can";
import McpContainerLogsModal from "@/components/mcp/McpContainerLogsModal";

/** Maps the shared add-server tabs (mirroring the MCP config modal) to deployment types. */
const DEPLOYMENT_TAB_ITEMS = [
  {
    key: "remote",
    type: McpDeploymentType.REMOTE_LINK,
    labelKey: "mcpConfig.addServer.title",
    Icon: Unplug,
  },
  {
    key: "container",
    type: McpDeploymentType.CONTAINER,
    labelKey: "mcpConfig.addContainer.title",
    Icon: Container,
  },
  {
    key: "openapi",
    type: McpDeploymentType.API,
    labelKey: "mcpConfig.openApiToMcp.title",
    Icon: Import,
  },
  {
    key: "upload",
    type: McpDeploymentType.LOCAL_IMAGE,
    labelKey: "mcpConfig.uploadImage.title",
    Icon: UploadIcon,
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
  onSubmittingChange?: (submitting: boolean) => void;
}

export default function AddMcpServiceLocalSection({
  active,
  enableUploadImage = false,
  onAdded,
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
  const { user } = useAuthorizationContext();
  const tenantId = user?.tenantId || null;
  const { data: groupData } = useGroupList(tenantId);
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
    form.setFieldValue("ingroup_permission", "READ_ONLY");
    form.setFieldValue("group_ids", []);
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
      form.setFieldValue("group_ids", []);
    }
  };

  const handleSubmit = async () => {
    try {
      await form.validateFields(
        VALIDATION_FIELDS_BY_DEPLOYMENT[deploymentType]
      );
    } catch {
      return;
    }
    const isContainerDeployment =
      deploymentType === McpDeploymentType.CONTAINER ||
      deploymentType === McpDeploymentType.LOCAL_IMAGE;
    if (isContainerDeployment) {
      setDeploymentStarted(true);
      setDeployedContainerId(null);
    }
    await submit(draft);
  };

  const renderDescriptionInput = () => (
    <Form.Item
      name="description"
      rules={rules.description}
      className="mb-0"
      style={{ marginBottom: 0 }}
    >
      <Input
        placeholder={t("mcpTools.detail.serviceDescription")}
        {...bindField("description")}
      />
    </Form.Item>
  );

  if (!active) return null;

  const isApi = deploymentType === McpDeploymentType.API;
  const isLocalImage = deploymentType === McpDeploymentType.LOCAL_IMAGE;
  const isGroupSelectDisabled = draft.ingroupPermission === "PRIVATE" || isApi;

  return (
    <div className="flex flex-col">
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        className="space-y-5 px-6 py-5"
      >
        <Tabs
          activeKey={activeTabKey}
          onChange={handleTabChange}
          size="small"
          items={deploymentTabItems.map(({ key, type, labelKey, Icon }) => ({
            key,
            label: (
              <span
                style={{ display: "inline-flex", alignItems: "center", gap: 8 }}
              >
                <Icon style={{ width: 16, height: 16 }} />
                {t(labelKey)}
              </span>
            ),
            children: (
              <Card size="small" style={{ marginTop: 8 }}>
                <Space
                  direction="vertical"
                  style={{ width: "100%" }}
                  size="small"
                >
                  {type === McpDeploymentType.REMOTE_LINK ? (
                    <>
                      <div
                        style={{
                          display: "flex",
                          gap: 8,
                          alignItems: "center",
                        }}
                      >
                        <Form.Item
                          name="name"
                          rules={rules.name}
                          className="mb-0"
                          style={{ flex: 0.8, marginBottom: 0 }}
                        >
                          <Input
                            placeholder={t(
                              "mcpConfig.addServer.namePlaceholder"
                            )}
                            {...bindField("name")}
                            maxLength={20}
                            autoComplete="off"
                          />
                        </Form.Item>
                        <Form.Item
                          name="serverUrl"
                          rules={rules.httpUrl}
                          className="mb-0"
                          style={{ flex: 3, marginBottom: 0 }}
                        >
                          <Input
                            placeholder={t(
                              "mcpConfig.addServer.urlPlaceholder"
                            )}
                            {...bindField("serverUrl")}
                            autoComplete="off"
                          />
                        </Form.Item>
                      </div>
                      {renderDescriptionInput()}
                      <Form.Item
                        name="customHeaders"
                        className="mb-0"
                        style={{ marginBottom: 0 }}
                      >
                        <Input.TextArea
                          placeholder={t(
                            "mcpConfig.addServer.customHeadersPlaceholder"
                          )}
                          {...bindField("customHeaders")}
                          rows={2}
                          style={{ fontSize: 14 }}
                        />
                      </Form.Item>
                      <div
                        style={{
                          display: "flex",
                          gap: 8,
                          alignItems: "center",
                        }}
                      >
                        <Form.Item
                          name="authorizationToken"
                          rules={rules.authToken}
                          className="mb-0"
                          style={{ flex: 1, marginBottom: 0 }}
                        >
                          <Input.Password
                            placeholder={t(
                              "mcpConfig.editServer.authorizationTokenPlaceholder"
                            )}
                            {...bindField("authorizationToken")}
                            autoComplete="new-password"
                          />
                        </Form.Item>
                      </div>
                    </>
                  ) : null}

                  {type === McpDeploymentType.CONTAINER ? (
                    <>
                      <div>
                        <Form.Item className="mb-0" style={{ marginBottom: 0 }}>
                          <div
                            style={{
                              fontSize: 12,
                              color: "rgba(0,0,0,0.45)",
                              display: "block",
                              marginBottom: 8,
                            }}
                          >
                            {t("mcpConfig.addContainer.configHint")}
                          </div>
                        </Form.Item>
                        <Form.Item
                          name="containerConfigJson"
                          rules={rules.containerConfig}
                          className="mb-0"
                          style={{ marginBottom: 0 }}
                        >
                          <Input.TextArea
                            placeholder={t(
                              "mcpConfig.addContainer.configPlaceholder"
                            )}
                            {...bindField("containerConfigJson")}
                            rows={6}
                            style={{ fontFamily: "monospace", fontSize: 12 }}
                          />
                        </Form.Item>
                      </div>
                      <div
                        style={{
                          display: "flex",
                          gap: 8,
                          alignItems: "center",
                        }}
                      >
                        <span style={{ minWidth: 80 }}>
                          {t("mcpConfig.addContainer.serviceName")}:
                        </span>
                        <Form.Item
                          name="name"
                          rules={rules.name}
                          className="mb-0"
                          style={{ marginBottom: 0 }}
                        >
                          <Input
                            placeholder={t(
                              "mcpConfig.addContainer.serviceNamePlaceholder"
                            )}
                            {...bindField("name")}
                            style={{ width: 150 }}
                            maxLength={20}
                          />
                        </Form.Item>
                        <span style={{ minWidth: 60 }}>
                          {t("mcpConfig.addContainer.port")}:
                        </span>
                        <InputNumber
                          placeholder={t(
                            "mcpConfig.addContainer.portPlaceholder"
                          )}
                          value={draft.containerPort}
                          onChange={(value) => {
                            const next = value === null ? undefined : value;
                            patchDraft({ containerPort: next });
                            form.setFieldValue("containerPort", next);
                          }}
                          min={1}
                          max={65535}
                          style={{ width: 120 }}
                          controls={false}
                        />
                        <div style={{ flex: 1 }} />
                      </div>
                      {renderDescriptionInput()}
                    </>
                  ) : null}

                  {type === McpDeploymentType.API ? (
                    <>
                      <div
                        style={{
                          display: "flex",
                          gap: 8,
                          alignItems: "center",
                        }}
                      >
                        <Form.Item
                          name="name"
                          rules={rules.name}
                          className="mb-0"
                          style={{ flex: 0.8, marginBottom: 0 }}
                        >
                          <Input
                            placeholder={t(
                              "mcpConfig.openapiService.form.serviceNamePlaceholder"
                            )}
                            {...bindField("name")}
                            maxLength={20}
                          />
                        </Form.Item>
                        <Form.Item
                          name="serverUrl"
                          rules={rules.httpUrl}
                          className="mb-0"
                          style={{ flex: 3, marginBottom: 0 }}
                        >
                          <Input
                            placeholder={t(
                              "mcpConfig.openapiService.form.serverUrlPlaceholder"
                            )}
                            {...bindField("serverUrl")}
                          />
                        </Form.Item>
                      </div>
                      {renderDescriptionInput()}
                      <Form.Item
                        name="customHeaders"
                        className="mb-0"
                        style={{ marginBottom: 0 }}
                      >
                        <Input.TextArea
                          placeholder={t(
                            "mcpConfig.addServer.customHeadersPlaceholder"
                          )}
                          {...bindField("customHeaders")}
                          rows={2}
                        />
                      </Form.Item>
                      <Form.Item
                        name="openApiJson"
                        rules={rules.openApiJson}
                        className="mb-0"
                        style={{ marginBottom: 0 }}
                      >
                        <Input.TextArea
                          placeholder={t(
                            "mcpConfig.openApiToMcp.jsonPlaceholder"
                          )}
                          {...bindField("openApiJson")}
                          rows={6}
                        />
                      </Form.Item>
                      <span style={{ fontSize: 12, color: "rgba(0,0,0,0.45)" }}>
                        {t("mcpConfig.openApiToMcp.form.apiJsonHint")}
                      </span>
                    </>
                  ) : null}

                  {type === McpDeploymentType.LOCAL_IMAGE ? (
                    <>
                      <div>
                        <Form.Item className="mb-0" style={{ marginBottom: 0 }}>
                          <div
                            style={{
                              fontSize: 12,
                              color: "rgba(0,0,0,0.45)",
                              display: "block",
                              marginBottom: 8,
                            }}
                          >
                            {t("mcpConfig.uploadImage.fileHint")}
                          </div>
                        </Form.Item>
                        <Form.Item
                          name="uploadImageFile"
                          className="mb-0"
                          style={{ marginBottom: 0 }}
                          rules={[
                            {
                              required: true,
                              message: t(
                                "mcpConfig.message.uploadImageFileRequired"
                              ),
                            },
                            {
                              validator: (_, value) => {
                                const fileName =
                                  value &&
                                  typeof value === "object" &&
                                  "name" in value
                                    ? String(value.name || "")
                                    : "";
                                if (fileName && !fileName.endsWith(".tar")) {
                                  return Promise.reject(
                                    new Error(
                                      t(
                                        "mcpConfig.message.uploadImageInvalidFileType"
                                      )
                                    )
                                  );
                                }
                                return Promise.resolve();
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
                              const file =
                                info.fileList[0]?.originFileObj ?? null;
                              patchDraft({
                                uploadImageFile: file as File | null,
                              });
                              form.setFieldValue("uploadImageFile", file);
                            }}
                          >
                            <Button icon={<UploadIcon size={16} />}>
                              {t("mcpConfig.uploadImage.button.selectFile")}
                            </Button>
                          </Upload>
                        </Form.Item>
                      </div>
                      <div
                        style={{
                          display: "flex",
                          gap: 8,
                          alignItems: "center",
                        }}
                      >
                        <InputNumber
                          placeholder={t(
                            "mcpConfig.uploadImage.portPlaceholder"
                          )}
                          value={draft.containerPort}
                          onChange={(value) => {
                            const next = value === null ? undefined : value;
                            patchDraft({ containerPort: next });
                            form.setFieldValue("containerPort", next);
                          }}
                          min={1}
                          max={65535}
                          style={{ width: 150 }}
                          controls={false}
                        />
                        <Form.Item
                          name="name"
                          rules={rules.name}
                          className="mb-0"
                          style={{ flex: 1, marginBottom: 0 }}
                        >
                          <Input
                            placeholder={t(
                              "mcpConfig.uploadImage.serviceNamePlaceholder"
                            )}
                            {...bindField("name")}
                          />
                        </Form.Item>
                      </div>
                      {renderDescriptionInput()}
                      <div
                        style={{
                          display: "flex",
                          gap: 8,
                          alignItems: "center",
                        }}
                      >
                        <Form.Item
                          name="authorizationToken"
                          rules={rules.authToken}
                          className="mb-0"
                          style={{ flex: 1, marginBottom: 0 }}
                        >
                          <Input.Password
                            placeholder={t(
                              "mcpConfig.editServer.authorizationTokenPlaceholder"
                            )}
                            {...bindField("authorizationToken")}
                            autoComplete="new-password"
                          />
                        </Form.Item>
                      </div>
                    </>
                  ) : null}
                </Space>
              </Card>
            ),
          }))}
        />

        <Can permission="group:read">
          <div className="mt-8 grid grid-cols-2 gap-4">
            <Form.Item
              name="group_ids"
              label={t("tenantResources.knowledgeBase.groupNames")}
              className="mb-0"
              help={
                isApi ? (
                  <span style={{ fontSize: 12, color: "rgba(0,0,0,0.45)" }}>
                    {t("mcpTools.detail.groupPermissionUnsupported")}
                  </span>
                ) : undefined
              }
            >
              <Select
                mode="multiple"
                showSearch={{ optionFilterProp: "label" }}
                placeholder={
                  isGroupSelectDisabled
                    ? t("knowledgeBase.create.permission.groupPlaceholder")
                    : t("tenantResources.knowledgeBase.groupNames")
                }
                value={isGroupSelectDisabled ? [] : draft.groupIds}
                options={groups.map(
                  (group: { group_id: number; group_name: string }) => ({
                    label: group.group_name,
                    value: group.group_id,
                  })
                )}
                disabled={isGroupSelectDisabled}
                onChange={(values: number[]) =>
                  patchDraft({ groupIds: values })
                }
                className="rounded-md"
              />
            </Form.Item>
            <Can permission="kb.groups:read">
              <Form.Item
                name="ingroup_permission"
                label={t("tenantResources.knowledgeBase.permission")}
                className="mb-0"
              >
                <Select
                  value={draft.ingroupPermission ?? "READ_ONLY"}
                  onChange={handlePermissionChange}
                  disabled={isApi}
                  options={[
                    {
                      value: "READ_ONLY",
                      label: t("knowledgeBase.ingroup.permission.READ_ONLY"),
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
          </div>
        </Can>
      </Form>

      <div className="flex items-center justify-between border-t border-slate-100 bg-white px-6 py-4">
        <div>
          {deploymentStarted ? (
            <Button onClick={() => setLogsOpen(true)}>
              {t("mcpTools.detail.viewContainerLogs")}
            </Button>
          ) : null}
        </div>
        <Button
          type="primary"
          onClick={handleSubmit}
          loading={submitting}
          disabled={isLocalImage && !draft.uploadImageFile}
        >
          {t("mcpTools.addModal.saveAndAdd")}
        </Button>
      </div>

      {deploymentStarted ? (
        <McpContainerLogsModal
          open={logsOpen}
          onCancel={() => setLogsOpen(false)}
          containerId={deployedContainerId}
        />
      ) : null}
    </div>
  );
}
