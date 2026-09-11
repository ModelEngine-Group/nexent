"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import {
  Button,
  Collapse,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Tooltip,
  Upload,
  message,
} from "antd";
import {
  InboxOutlined,
  QuestionCircleOutlined,
  SettingOutlined,
} from "@ant-design/icons";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import type { AidpModelItem } from "@/ext_components/aidp/services/aidpKnowledgeService";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";
import { USER_ROLES } from "@/const/auth";
import {
  AIDP_ACCEPT_STRING,
  AIDP_KNOWLEDGE_BASE_NAME_PATTERN,
} from "@/const/knowledgeBase";
import {
  partitionAidpFiles,
  validateAidpFiles,
} from "@/services/uploadService";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";

const { Dragger } = Upload;

const PREFERRED_VLM_MODEL = "Qwen3-VL-8B-Instruct";

const AIDP_CREATE_DEFAULTS = {
  chunk_token_num: 1024,
  chunk_overlap_num: 128,
  embedding_model: "default",
  is_personal: 0,
  topk: 10,
  similarity: 0.0,
  smartsplit: 1,
  caption_enable: 0,
};

interface AidpCreateKbModalProps {
  open: boolean;
  existingKbs: AidpKnowledgeBaseItem[];
  onCancel: () => void;
  onSuccess: (knowledgeBase: AidpKnowledgeBaseItem) => void;
}

const AidpCreateKbModal: React.FC<AidpCreateKbModalProps> = ({
  open,
  existingKbs,
  onCancel,
  onSuccess,
}) => {
  const { t, i18n } = useTranslation();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [fileList, setFileList] = useState<File[]>([]);
  const fileListRef = useRef<File[]>([]);
  const pendingFilesRef = useRef<File[]>([]);
  const rafIdRef = useRef<number | null>(null);

  useEffect(() => {
    fileListRef.current = fileList;
  }, [fileList]);

  const { user } = useAuthorizationContext();
  const isUser = user?.role === USER_ROLES.USER;
  const canConfigureGroupPermissions = !!user && !isUser;
  const tenantId = user?.tenantId ?? null;
  const { data: groupListData } = useGroupList(
    canConfigureGroupPermissions ? tenantId : null
  );
  const groupOptions = useMemo(
    () =>
      (groupListData?.groups ?? []).map((group) => ({
        value: group.group_id,
        label: group.group_name,
      })),
    [groupListData]
  );

  const captionEnabled = Form.useWatch("caption_enable", form);
  const ingroupPermission = Form.useWatch("ingroup_permission", form);

  useEffect(() => {
    if (!open) return;
    form.setFieldsValue({
      chunk_token_num: AIDP_CREATE_DEFAULTS.chunk_token_num,
      chunk_overlap_num: AIDP_CREATE_DEFAULTS.chunk_overlap_num,
      caption_enable: AIDP_CREATE_DEFAULTS.caption_enable === 1,
      ingroup_permission: isUser ? "PRIVATE" : "READ_ONLY",
      group_ids: [],
    });
  }, [form, isUser, open]);

  const { data: vlmModelsData, isLoading: vlmModelsLoading } = useQuery({
    queryKey: ["aidp-models", "llm", "KnowledgeBase"],
    queryFn: () => aidpKnowledgeService.listModels("llm", "KnowledgeBase"),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  });

  const vlmModelOptions = useMemo(() => {
    const models: AidpModelItem[] = vlmModelsData?.models ?? [];
    return models
      .map((model) => model.model_name)
      .filter((name): name is string => Boolean(name));
  }, [vlmModelsData]);

  const defaultVlmModel = useMemo(() => {
    if (vlmModelOptions.length === 0) return PREFERRED_VLM_MODEL;
    return vlmModelOptions.includes(PREFERRED_VLM_MODEL)
      ? PREFERRED_VLM_MODEL
      : vlmModelOptions[0];
  }, [vlmModelOptions]);

  useEffect(() => {
    if (!open || !defaultVlmModel) return;
    const currentModel = form.getFieldValue("vlm_model");
    if (!currentModel || !vlmModelOptions.includes(currentModel)) {
      form.setFieldValue("vlm_model", defaultVlmModel);
    }
  }, [defaultVlmModel, form, open, vlmModelOptions]);

  const existingNames = useMemo(
    () =>
      new Set(
        (existingKbs || [])
          .map((kb) => kb.kds_name?.toLowerCase().trim())
          .filter((name): name is string => Boolean(name))
      ),
    [existingKbs]
  );

  const handleSubmit = async () => {
    let knowledgeBaseCreated = false;
    let createdKnowledgeBase: AidpKnowledgeBaseItem | null = null;

    try {
      const values = await form.validateFields();
      const name = values.name.trim();

      if (existingNames.has(name.toLowerCase())) {
        message.error(t("aidpKnowledge.createDuplicateName", { name }));
        return;
      }

      if (fileList.length > 0) {
        const validation = validateAidpFiles(fileList);
        if (validation.valid.length !== fileList.length) {
          partitionAidpFiles(fileList, t, message);
          return;
        }
      }

      setLoading(true);
      const permission = isUser
        ? "PRIVATE"
        : values.ingroup_permission || "READ_ONLY";
      const groupIds =
        isUser || permission === "PRIVATE"
          ? []
          : Array.isArray(values.group_ids)
            ? values.group_ids
            : [];
      const captionEnable = values.caption_enable ? 1 : 0;

      const created = await aidpKnowledgeService.createKb({
        name,
        description: values.description?.trim() || "",
        chunk_token_num:
          values.chunk_token_num ?? AIDP_CREATE_DEFAULTS.chunk_token_num,
        chunk_overlap_num:
          values.chunk_overlap_num ?? AIDP_CREATE_DEFAULTS.chunk_overlap_num,
        embedding_model: AIDP_CREATE_DEFAULTS.embedding_model,
        vlm_model: captionEnable
          ? values.vlm_model || defaultVlmModel || ""
          : "",
        is_personal: AIDP_CREATE_DEFAULTS.is_personal,
        topk: AIDP_CREATE_DEFAULTS.topk,
        similarity: AIDP_CREATE_DEFAULTS.similarity,
        smartsplit: AIDP_CREATE_DEFAULTS.smartsplit,
        caption_enable: captionEnable,
        ingroup_permission: permission,
        group_ids: groupIds,
      });
      knowledgeBaseCreated = true;
      createdKnowledgeBase = {
        ...created,
        kds_id: String(created.kds_id || ""),
        kds_name: created.kds_name || name,
        description: created.description ?? values.description?.trim() ?? "",
        permission: "EDIT",
        ingroup_permission: permission,
        group_ids: groupIds,
        resource_status: "ACTIVE",
        is_multimodal: captionEnable === 1,
      };

      if (fileList.length > 0 && created.kds_id) {
        const result = await aidpKnowledgeService.uploadDocs(
          created.kds_id,
          fileList
        );
        const failureDetails = result.failed_list.map((item) => {
          const reason = i18n.language.startsWith("zh")
            ? item.reason_zh || item.reason_en
            : item.reason_en || item.reason_zh;
          return `${item.file_name}: ${reason || t("aidpKnowledge.uploadFailed")}`;
        });
        const failureLines = failureDetails.map((detail, index) => (
          <div key={`${index}-${detail}`}>{detail}</div>
        ));

        if (result.summary.failed > 0 && result.summary.success === 0) {
          message.warning(
            <div className="text-left">
              <div>{t("aidpKnowledge.createKbSuccess")}</div>
              {failureLines.length > 0 ? (
                failureLines
              ) : (
                <div>{t("aidpKnowledge.uploadFailed")}</div>
              )}
            </div>
          );
        } else if (result.summary.failed > 0) {
          message.info(
            <div className="text-left">
              <div>{t("aidpKnowledge.createKbSuccess")}</div>
              <div>
                {t("aidpKnowledge.uploadPartial", {
                  success: result.summary.success,
                  failed: result.summary.failed,
                })}
              </div>
              {failureLines}
            </div>
          );
        } else {
          message.success(
            `${t("aidpKnowledge.createKbSuccess")} | ${t(
              "aidpKnowledge.uploadSuccess",
              { count: result.summary.success }
            )}`
          );
        }
      } else {
        message.success(t("aidpKnowledge.createKbSuccess"));
      }

      handleReset();
      if (createdKnowledgeBase) onSuccess(createdKnowledgeBase);
    } catch (error) {
      const reason =
        error instanceof Error && error.message.trim()
          ? error.message
          : knowledgeBaseCreated
            ? t("aidpKnowledge.uploadFailed")
            : t("aidpKnowledge.createKbFailed");
      message.error(
        knowledgeBaseCreated
          ? `${t("aidpKnowledge.createKbSuccess")} | ${reason}`
          : reason
      );
      if (knowledgeBaseCreated) {
        handleReset();
        if (createdKnowledgeBase) onSuccess(createdKnowledgeBase);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    form.resetFields();
    setFileList([]);
    pendingFilesRef.current = [];
    if (rafIdRef.current !== null) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    }
  };

  const handleCancel = () => {
    handleReset();
    onCancel();
  };

  const addFiles = (files: File[]) => {
    const currentFiles = fileListRef.current;
    const existing = new Set(currentFiles.map((file) => file.name));
    const uniqueFiles = files.filter((file) => !existing.has(file.name));
    const { valid } = partitionAidpFiles(
      uniqueFiles,
      t,
      message,
      currentFiles.length
    );
    if (valid.length > 0) setFileList([...currentFiles, ...valid]);
  };

  const handleFileBeforeUpload = (file: File) => {
    pendingFilesRef.current.push(file);
    if (rafIdRef.current === null) {
      rafIdRef.current = requestAnimationFrame(() => {
        const batch = pendingFilesRef.current;
        pendingFilesRef.current = [];
        rafIdRef.current = null;
        addFiles(batch);
      });
    }
    return false;
  };

  return (
    <Modal
      open={open}
      title={null}
      onCancel={handleCancel}
      centered
      width={640}
      maskClosable={false}
      destroyOnHidden
      styles={{
        container: { overflow: "hidden", borderRadius: 16, padding: 0 },
        body: { padding: 0 },
        footer: {
          margin: 0,
          padding: "12px 20px 16px",
          borderTop: "1px solid #f0f0f0",
        },
      }}
      footer={
        <div className="flex justify-end gap-3">
          <Button onClick={handleCancel} disabled={loading}>
            {t("common.cancel")}
          </Button>
          <Button
            type="primary"
            loading={loading}
            onClick={() => void handleSubmit()}
          >
            {fileList.length > 0
              ? t("aidpKnowledge.createSubmit")
              : t("aidpKnowledge.createKb")}
          </Button>
        </div>
      }
    >
      <div>
        <div
          className="border-b border-gray-200"
          style={{ padding: "24px 24px 20px" }}
        >
          <h2 className="text-xl font-semibold tracking-tight text-gray-900">
            {t("aidpKnowledge.createKb")}
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            {t("knowledgeBase.create.subtitle")}
          </p>
        </div>

        <Form
          form={form}
          layout="vertical"
          style={{ padding: "20px 24px 8px" }}
        >
          <Form.Item
            name="name"
            label={t("aidpKnowledge.kbName")}
            rules={[
              { required: true, message: t("aidpKnowledge.kbNameRequired") },
              {
                pattern: AIDP_KNOWLEDGE_BASE_NAME_PATTERN,
                message: t("aidpKnowledge.kbNameInvalid"),
              },
            ]}
          >
            <Input placeholder={t("aidpKnowledge.kbNamePlaceholder")} />
          </Form.Item>

          <Form.Item
            name="description"
            label={t("aidpKnowledge.kbDescription")}
          >
            <Input.TextArea
              rows={3}
              placeholder={t("aidpKnowledge.kbDescriptionPlaceholder")}
            />
          </Form.Item>

          <div className="mb-5">
            <Dragger
              accept={AIDP_ACCEPT_STRING}
              multiple
              showUploadList={false}
              beforeUpload={handleFileBeforeUpload}
              disabled={loading}
              className="!rounded-xl !border-blue-200 !bg-blue-50/30"
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined className="!text-blue-500" />
              </p>
              <p className="ant-upload-text !text-sm !text-gray-700">
                {t("aidpKnowledge.uploadHint")}
              </p>
              <div className="ant-upload-hint mt-2 space-y-1 px-4 text-xs leading-5 text-gray-400">
                <div>{t("aidpKnowledge.uploadHintCount")}</div>
                <div>{t("aidpKnowledge.uploadHintSize")}</div>
                <div className="break-all">
                  {t("aidpKnowledge.uploadHintFormats")}
                </div>
              </div>
            </Dragger>

            {fileList.length > 0 ? (
              <div className="mt-3 space-y-2">
                {fileList.map((file) => (
                  <div
                    key={`${file.name}-${file.lastModified}`}
                    className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm"
                  >
                    <span
                      className="min-w-0 truncate text-gray-700"
                      title={file.name}
                    >
                      {file.name}
                    </span>
                    <button
                      type="button"
                      className="ml-3 shrink-0 text-gray-400 hover:text-red-500"
                      aria-label={file.name}
                      onClick={() =>
                        setFileList((current) =>
                          current.filter(
                            (item) =>
                              item.name !== file.name ||
                              item.lastModified !== file.lastModified
                          )
                        )
                      }
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="mt-2 text-center text-xs text-gray-400">
                {t("aidpKnowledge.createNoFiles")}
              </div>
            )}
          </div>

          <Collapse
            className="!rounded-xl !border-gray-200"
            items={[
              {
                key: "advanced",
                label: (
                  <span className="flex items-center gap-2 text-sm font-medium text-gray-800">
                    <SettingOutlined />
                    {t("aidpKnowledge.createAdvancedOptions")}
                  </span>
                ),
                children: (
                  <div className="space-y-1">
                    <Form.Item
                      name="chunk_token_num"
                      label={t("aidpKnowledge.createChunkTokenNum")}
                      rules={[
                        {
                          required: true,
                          message: t(
                            "aidpKnowledge.createChunkTokenNumRequired"
                          ),
                        },
                        {
                          type: "number",
                          min: 1,
                          message: t("aidpKnowledge.createChunkTokenNumMin"),
                        },
                      ]}
                    >
                      <InputNumber style={{ width: "100%" }} min={1} />
                    </Form.Item>

                    <Form.Item
                      name="chunk_overlap_num"
                      label={t("aidpKnowledge.createChunkOverlapNum")}
                      rules={[
                        {
                          required: true,
                          message: t(
                            "aidpKnowledge.createChunkOverlapNumRequired"
                          ),
                        },
                        {
                          type: "number",
                          min: 0,
                          message: t("aidpKnowledge.createChunkOverlapNumMin"),
                        },
                      ]}
                    >
                      <InputNumber style={{ width: "100%" }} min={0} />
                    </Form.Item>

                    {canConfigureGroupPermissions && (
                      <>
                        <Form.Item
                          name="ingroup_permission"
                          label={t("aidpKnowledge.createIngroupPermission")}
                          rules={[
                            {
                              required: true,
                              message: t(
                                "aidpKnowledge.createIngroupPermissionRequired"
                              ),
                            },
                          ]}
                        >
                          <Select
                            options={[
                              {
                                value: "EDIT",
                                label: t(
                                  "aidpKnowledge.createIngroupPermissionEdit"
                                ),
                              },
                              {
                                value: "READ_ONLY",
                                label: t(
                                  "aidpKnowledge.createIngroupPermissionRead"
                                ),
                              },
                              {
                                value: "PRIVATE",
                                label: t(
                                  "aidpKnowledge.createIngroupPermissionPrivate"
                                ),
                              },
                            ]}
                          />
                        </Form.Item>
                        <Form.Item
                          name="group_ids"
                          label={t("aidpKnowledge.createAccessGroups")}
                          required={ingroupPermission !== "PRIVATE"}
                          dependencies={["ingroup_permission"]}
                          rules={[
                            ({ getFieldValue }) => ({
                              validator(_rule, value) {
                                const level =
                                  getFieldValue("ingroup_permission") ||
                                  "READ_ONLY";
                                if (level === "PRIVATE")
                                  return Promise.resolve();
                                if (Array.isArray(value) && value.length > 0) {
                                  return Promise.resolve();
                                }
                                return Promise.reject(
                                  new Error(
                                    t(
                                      "aidpKnowledge.createAccessGroupsRequired"
                                    )
                                  )
                                );
                              },
                            }),
                          ]}
                        >
                          <Select
                            mode="multiple"
                            placeholder={t(
                              "aidpKnowledge.createAccessGroupsPlaceholder"
                            )}
                            disabled={ingroupPermission === "PRIVATE"}
                            options={groupOptions}
                          />
                        </Form.Item>
                      </>
                    )}

                    <Form.Item
                      name="caption_enable"
                      valuePropName="checked"
                      label={
                        <Space>
                          <span>{t("aidpKnowledge.createCaptionEnable")}</span>
                          <Tooltip
                            title={t("aidpKnowledge.createCaptionEnableHint")}
                          >
                            <QuestionCircleOutlined className="text-gray-400" />
                          </Tooltip>
                        </Space>
                      }
                    >
                      <Switch />
                    </Form.Item>

                    {captionEnabled && (
                      <Form.Item
                        name="vlm_model"
                        label={
                          <Space>
                            <span>{t("aidpKnowledge.createVlmModel")}</span>
                            <Tooltip
                              title={t("aidpKnowledge.createVlmModelHint")}
                            >
                              <QuestionCircleOutlined className="text-gray-400" />
                            </Tooltip>
                          </Space>
                        }
                      >
                        <Select
                          showSearch
                          allowClear
                          loading={vlmModelsLoading}
                          notFoundContent={
                            vlmModelsLoading
                              ? t("aidpKnowledge.createVlmModelLoading")
                              : t("aidpKnowledge.createVlmModelNone")
                          }
                          placeholder={t("aidpKnowledge.createVlmModelSearch")}
                          options={vlmModelOptions.map((name) => ({
                            label: name,
                            value: name,
                          }))}
                          filterOption={(input, option) =>
                            (option?.label as string)
                              ?.toLowerCase()
                              .includes(input.toLowerCase()) ?? false
                          }
                        />
                      </Form.Item>
                    )}
                  </div>
                ),
              },
            ]}
          />
        </Form>
      </div>
    </Modal>
  );
};

export default AidpCreateKbModal;
