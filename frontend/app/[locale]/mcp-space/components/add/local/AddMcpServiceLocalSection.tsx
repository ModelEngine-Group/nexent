import { useState } from "react";
import { Alert, Button, Form, Input, Upload } from "antd";
import type { UploadFile } from "antd";
import { ApiOutlined, CloudOutlined, ContainerOutlined, LinkOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { McpDeploymentType, McpTransportType } from "@/const/mcpTools";
import type { LocalAddMcpDraft } from "@/types/mcpTools";
import { useMcpAddLocal } from "@/hooks/mcpTools/useMcpAddLocal";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import ContainerPortField from "../../shared/ContainerPortField";
import TagEditor from "../../shared/TagEditor";

const DEPLOYMENT_OPTIONS = [
  {
    value: McpDeploymentType.REMOTE_LINK,
    labelKey: "mcpTools.deploymentType.remoteLink",
    Icon: LinkOutlined,
  },
  {
    value: McpDeploymentType.CONTAINER,
    labelKey: "mcpTools.deploymentType.container",
    Icon: ContainerOutlined,
  },
  {
    value: McpDeploymentType.API,
    labelKey: "mcpTools.deploymentType.api",
    Icon: ApiOutlined,
  },
  {
    value: McpDeploymentType.LOCAL_IMAGE,
    labelKey: "mcpTools.deploymentType.localImage",
    Icon: CloudOutlined,
  },
] as const;

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
});

interface AddMcpServiceLocalSectionProps {
  active: boolean;
  enableUploadImage?: boolean;
  onAdded: () => void;
}

export default function AddMcpServiceLocalSection({
  active,
  enableUploadImage = false,
  onAdded,
}: AddMcpServiceLocalSectionProps) {
  const { t } = useTranslation("common");
  const rules = useMcpFormRules();
  const [form] = Form.useForm();
  const [draft, setDraft] = useState<LocalAddMcpDraft>(() => createInitialDraft());
  const [deploymentType, setDeploymentType] = useState<McpDeploymentType>(
    McpDeploymentType.REMOTE_LINK
  );
  const { submit, submitting } = useMcpAddLocal({
    onSuccess: () => {
      setDraft(createInitialDraft());
      setDeploymentType(McpDeploymentType.REMOTE_LINK);
      form.resetFields();
      onAdded();
    },
  });

  const patchDraft = (patch: Partial<LocalAddMcpDraft>) => {
    setDraft((prev) => ({ ...prev, ...patch }));
  };

  const deploymentOptions = enableUploadImage
    ? DEPLOYMENT_OPTIONS
    : DEPLOYMENT_OPTIONS.filter(
        (option) => option.value !== McpDeploymentType.LOCAL_IMAGE
      );

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
          ? (eventOrValue as { target: { value: LocalAddMcpDraft[K] } }).target.value
          : (eventOrValue as LocalAddMcpDraft[K]);
      patchDraft({ [key]: next } as Partial<LocalAddMcpDraft>);
      form.setFieldValue(key as string, next);
    },
  });

  const addTag = (tag: string) => {
    const next = (tag || "").trim();
    if (!next || draft.tags.includes(next)) return;
    patchDraft({ tags: [...draft.tags, next] });
  };

  const removeTag = (index: number) => {
    patchDraft({ tags: draft.tags.filter((_, i) => i !== index) });
  };

  const handleSubmit = async () => {
    try {
      await form.validateFields();
    } catch {
      return;
    }
    await submit(draft);
  };

  if (!active) return null;

  const isRemoteLink = deploymentType === McpDeploymentType.REMOTE_LINK;
  const isContainer = deploymentType === McpDeploymentType.CONTAINER;
  const isApi = deploymentType === McpDeploymentType.API;
  const isLocalImage = deploymentType === McpDeploymentType.LOCAL_IMAGE;

  return (
    <div className="flex h-full flex-col">
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        className="flex-1 space-y-5 px-6 py-5"
      >
        {/* Deployment type selector */}
        <div>
          <label className="mb-2 block text-sm font-medium text-slate-700">
            {t("mcpTools.detail.addMethod")}
          </label>
          <div className="grid grid-cols-4 gap-3">
            {deploymentOptions.map(({ value, labelKey, Icon }) => {
              const selected = deploymentType === value;
              return (
                <button
                  key={value}
                  type="button"
                  onClick={() => {
                    setDeploymentType(value);
                    const nextTransport =
                      value === McpDeploymentType.CONTAINER ||
                      value === McpDeploymentType.LOCAL_IMAGE
                        ? McpTransportType.CONTAINER
                        : McpTransportType.URL;
                    patchDraft({
                      deploymentType: value,
                      transportType: nextTransport,
                      uploadImageFile:
                        value === McpDeploymentType.LOCAL_IMAGE
                          ? draft.uploadImageFile
                          : null,
                    });
                    form.setFieldValue("transportType", nextTransport);
                  }}
                  className={`flex h-20 flex-col items-center justify-center gap-2 rounded-xl border text-sm transition ${
                    selected
                      ? "border-blue-500 bg-blue-50 text-blue-600 shadow-sm"
                      : "border-slate-200 bg-white text-slate-600 hover:border-blue-200 hover:bg-blue-50/40"
                  }`}
                >
                  <Icon className="text-xl" />
                  <span>{t(labelKey)}</span>
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">
            {t("mcpTools.detail.serviceName")}
          </label>
          <Form.Item name="name" rules={rules.name} className="mb-0">
            <Input {...bindField("name")} className="w-full rounded-md" />
          </Form.Item>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">
            {t("mcpTools.detail.serviceDescription")}
          </label>
          <Form.Item name="description" rules={rules.description} className="mb-0">
            <Input.TextArea
              {...bindField("description")}
              autoSize={{ minRows: 4, maxRows: 10 }}
              className="w-full rounded-md"
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
                <Form.Item name="serverUrl" rules={rules.httpUrl} className="mb-0">
                  <Input
                    {...bindField("serverUrl")}
                    className="w-full rounded-md"
                    placeholder={t("mcpTools.addModal.serverUrl")}
                  />
                </Form.Item>
              </div>

              <div>
                <label className="mb-1 block text-sm font-normal text-slate-500">
                  {t("mcpTools.addModal.bearerTokenOptional")}
                </label>
                <Form.Item name="authorizationToken" rules={rules.authToken} className="mb-0">
                  <Input
                    {...bindField("authorizationToken")}
                    className="w-full rounded-md"
                    placeholder={t("mcpTools.addModal.bearerTokenPlaceholder")}
                  />
                </Form.Item>
              </div>

              <div>
                <label className="mb-1 block text-sm font-normal text-slate-500">
                  {t("mcpTools.addModal.customHeaders")}
                </label>
                <Form.Item name="customHeaders" className="mb-0">
                  <Input.TextArea
                    {...bindField("customHeaders")}
                    rows={2}
                    className="w-full rounded-md"
                    placeholder={t("mcpTools.addModal.customHeadersPlaceholder")}
                  />
                </Form.Item>
              </div>
            </div>
          </div>
        ) : isContainer ? (
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              {t("mcpTools.detail.serviceConfigTitle")}
            </label>
            <div className="space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
              <div>
                <label className="mb-1 block text-sm font-normal text-slate-500">
                  {t("mcpTools.addModal.containerConfig")}
                </label>
                <Form.Item name="containerConfigJson" rules={rules.containerConfig} className="mb-0">
                  <Input.TextArea
                    {...bindField("containerConfigJson")}
                    rows={5}
                    placeholder={t("mcpTools.addModal.containerConfigPlaceholder")}
                    className="w-full"
                  />
                </Form.Item>
              </div>

              <Form.Item name="containerPort" rules={rules.containerPort} className="mb-0">
                <div>
                  <ContainerPortField
                    scope="local"
                    containerPort={draft.containerPort}
                    setContainerPort={(value) => {
                      patchDraft({ containerPort: value });
                      form.setFieldValue("containerPort", value);
                    }}
                  />
                </div>
              </Form.Item>
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
                  {t("mcpTools.addModal.serverUrl")}
                </label>
                <Form.Item name="serverUrl" rules={rules.httpUrl} className="mb-0">
                  <Input
                    {...bindField("serverUrl")}
                    className="w-full rounded-md"
                    placeholder={t("mcpTools.addModal.serverUrl")}
                  />
                </Form.Item>
              </div>

              <div>
                <label className="mb-1 block text-sm font-normal text-slate-500">
                  {t("mcpConfig.addServer.customHeaders")}
                </label>
                <Form.Item name="customHeaders" className="mb-0">
                  <Input.TextArea
                    {...bindField("customHeaders")}
                    rows={2}
                    className="w-full rounded-md"
                    placeholder={t("mcpConfig.addServer.customHeadersPlaceholder")}
                  />
                </Form.Item>
              </div>

              <div>
                <label className="mb-1 block text-sm font-normal text-slate-500">
                  {t("mcpConfig.openapiService.form.openapiJson")}
                </label>
                <Form.Item name="openApiJson" className="mb-0">
                  <Input.TextArea
                    {...bindField("openApiJson")}
                    rows={6}
                    className="w-full rounded-md"
                    placeholder={t("mcpConfig.openApiToMcp.jsonPlaceholder")}
                  />
                </Form.Item>
              </div>
            </div>
          </div>
        ) : null}

        {isLocalImage ? (
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              {t("mcpTools.detail.serviceConfigTitle")}
            </label>
            <div className="space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
              <div>
                <label className="mb-1 block text-sm font-normal text-slate-500">
                  {t("mcpConfig.uploadImage.filePlaceholder")}
                </label>
                <Form.Item
                  name="uploadImageFile"
                  className="mb-0"
                  rules={[
                    {
                      required: true,
                      message: t("mcpConfig.message.uploadImageFileRequired"),
                    },
                    {
                      validator: (_, value: File | null | undefined) => {
                        if (value && !value.name.endsWith(".tar")) {
                          return Promise.reject(
                            new Error(t("mcpConfig.message.uploadImageInvalidFileType"))
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
                      const file = info.fileList[0]?.originFileObj ?? null;
                      patchDraft({ uploadImageFile: file as File | null });
                      form.setFieldValue("uploadImageFile", file);
                    }}
                  >
                    <Button>{t("mcpConfig.uploadImage.button.selectFile")}</Button>
                  </Upload>
                </Form.Item>
                <p className="mt-1 text-xs text-slate-400">
                  {t("mcpConfig.uploadImage.fileHint")}
                </p>
              </div>

              <Form.Item name="containerPort" rules={rules.containerPort} className="mb-0">
                <div>
                  <ContainerPortField
                    scope="local"
                    containerPort={draft.containerPort}
                    setContainerPort={(value) => {
                      patchDraft({ containerPort: value });
                      form.setFieldValue("containerPort", value);
                    }}
                  />
                </div>
              </Form.Item>

              <div>
                <label className="mb-1 block text-sm font-normal text-slate-500">
                  {t("mcpTools.addModal.bearerTokenOptional")}
                </label>
                <Form.Item name="authorizationToken" rules={rules.authToken} className="mb-0">
                  <Input
                    {...bindField("authorizationToken")}
                    className="w-full rounded-md"
                    placeholder={t("mcpTools.addModal.bearerTokenPlaceholder")}
                  />
                </Form.Item>
              </div>
            </div>
          </div>
        ) : null}

        <div className="grid grid-cols-[1fr_160px] gap-4">
          <TagEditor
            title={t("mcpTools.detail.tags")}
            titleClassName="mb-1 block text-sm font-medium text-slate-700"
            tags={draft.tags}
            onAddTag={(tag) => addTag(tag || "")}
            onRemoveTag={removeTag}
            removeAriaKey="mcpTools.detail.removeTagAria"
            placeholderKey="mcpTools.detail.tagInputPlaceholder"
          />

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              {t("mcpTools.detail.versionNumber")}
            </label>
            <Form.Item name="version" className="mb-0" rules={rules.version}>
              <Input {...bindField("version")} className="w-full rounded-md" placeholder="1.0.0" />
            </Form.Item>
          </div>
        </div>
      </Form>

      <div className="sticky bottom-0 flex items-center justify-between border-t border-slate-100 bg-white px-6 py-4">
        <div />
        <Button type="primary" onClick={handleSubmit} loading={submitting} disabled={isLocalImage && !draft.uploadImageFile}>
          {t("mcpTools.addModal.saveAndAdd")}
        </Button>
      </div>
    </div>
  );
}
