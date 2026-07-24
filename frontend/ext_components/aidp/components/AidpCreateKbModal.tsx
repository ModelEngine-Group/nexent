"use client";

import React, { useState, useMemo, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import {
  Modal,
  Form,
  Input,
  InputNumber,
  Steps,
  Upload,
  Button,
  message,
  Space,
  Divider,
  Collapse,
  Switch,
  Tooltip,
  Select,
} from "antd";
import { InboxOutlined, QuestionCircleOutlined } from "@ant-design/icons";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import type { AidpModelItem } from "@/services/aidpKnowledgeService";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";

const { Dragger } = Upload;

// Preferred VLM model name when present in AIDP's available list.
// Falls back to the first model in the list if this specific one is absent.
const PREFERRED_VLM_MODEL = "Qwen3-VL-8B-Instruct";

/**
 * Default AIDP knowledge base configuration.
 * Aligned with sdk/nexent/core/knowledge_base/config.py (build_create_payload defaults).
 *
 * Required fields per AIDP schema:
 *   chunk_token_num (> 0), chunk_overlap_num (>= 0)
 * Reference fills the rest (is_personal, topk, similarity, smartsplit, caption_enable).
 * ``vlm_model`` is no longer a hardcoded constant — it is resolved at runtime
 * from the list of models AIDP advertises as applicable to the KnowledgeBase
 * application (see ``useQuery(["aidp-models"])``).
 */
const AIDP_CREATE_DEFAULTS = {
  chunk_token_num: 1024,
  chunk_overlap_num: 128,
  embedding_model: "default",
  is_personal: 0,
  topk: 10,
  similarity: 0.0,
  smartsplit: 1,
  // caption_enable: int 0/1.
  caption_enable: 0,
};

interface AidpCreateKbModalProps {
  open: boolean;
  existingKbs: AidpKnowledgeBaseItem[];
  onCancel: () => void;
  onSuccess: (newKdsId: string) => void;
}

const AidpCreateKbModal: React.FC<AidpCreateKbModalProps> = ({
  open,
  existingKbs,
  onCancel,
  onSuccess,
}) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [current, setCurrent] = useState(0);
  const [loading, setLoading] = useState(false);
  const [fileList, setFileList] = useState<File[]>([]);

  // Load the tenant's groups so the user can pick which groups may access
  // the new KB. When no tenant context is available we fall back to an
  // empty list and disable the group picker.
  // NOTE: ``useAuthorizationContext`` is required — it is the only context
  // that exposes ``user: User | null`` (with ``tenantId``). The similarly-
  // named ``useAuthenticationContext`` only carries ``session`` and the
  // plain ``useAuthentication`` hook doesn't carry ``user`` at all.
  const { user } = useAuthorizationContext();
  const tenantId = user?.tenantId ?? null;
  const { data: groupListData } = useGroupList(tenantId);
  const groupOptions = useMemo(
    () =>
      (groupListData?.groups ?? []).map((g) => ({
        value: g.group_id,
        label: g.group_name,
      })),
    [groupListData]
  );
  const [formValues, setFormValues] = useState<{
    name: string;
    description?: string;
    vlm_model?: string;
    chunk_token_num: number;
    chunk_overlap_num: number;
    caption_enable: number;
    ingroup_permission: "EDIT" | "READ_ONLY" | "PRIVATE";
    group_ids: number[];
  }>({
    name: "",
    chunk_token_num: AIDP_CREATE_DEFAULTS.chunk_token_num,
    chunk_overlap_num: AIDP_CREATE_DEFAULTS.chunk_overlap_num,
    caption_enable: AIDP_CREATE_DEFAULTS.caption_enable,
    ingroup_permission: "READ_ONLY",
    group_ids: [],
  });

  // Drive the vlm_model dropdown's visibility off the live Switch value.
  // useWatch gives us a re-render whenever caption_enable toggles, without
  // forcing the user to manually sync the form value to local state.
  const captionEnabled = Form.useWatch("caption_enable", form);

  // Fetch applicable VLM models from AIDP. Only run when modal is open to
  // avoid hitting the (relatively slow) admin endpoint unnecessarily.
  const { data: vlmModelsData, isLoading: vlmModelsLoading } = useQuery({
    queryKey: ["aidp-models", "llm", "KnowledgeBase"],
    queryFn: () => aidpKnowledgeService.listModels("llm", "KnowledgeBase"),
    enabled: open,
    staleTime: 5 * 60 * 1000, // 5 min
  });

  const vlmModelOptions = useMemo(() => {
    const models: AidpModelItem[] = vlmModelsData?.models ?? [];
    return models
      .map((m) => m.model_name)
      .filter((name): name is string => typeof name === "string" && name.length > 0);
  }, [vlmModelsData]);

  // Resolve the default VLM model: prefer the hardcoded
  // PREFERRED_VLM_MODEL if present, otherwise the first in the list.
  // Falls back to PREFERRED_VLM_MODEL (sent to AIDP as-is) when the
  // models endpoint returns empty, matching the previous behavior.
  const defaultVlmModel = useMemo(() => {
    if (vlmModelOptions.length === 0) return PREFERRED_VLM_MODEL;
    if (vlmModelOptions.includes(PREFERRED_VLM_MODEL)) return PREFERRED_VLM_MODEL;
    return vlmModelOptions[0];
  }, [vlmModelOptions]);

  // Pre-populate vlm_model on the form whenever the default is resolved,
  // so the user sees a meaningful default on first open.
  useEffect(() => {
    if (!open) return;
    if (!defaultVlmModel) return;
    const current = form.getFieldValue("vlm_model");
    if (!current || !vlmModelOptions.includes(current)) {
      form.setFieldValue("vlm_model", defaultVlmModel);
    }
  }, [open, defaultVlmModel, vlmModelOptions, form]);

  // Duplicate name check against existing KBs
  const existingNames = useMemo(
    () =>
      new Set(
        (existingKbs || [])
          .map((kb) => kb.kds_name?.toLowerCase().trim())
          .filter((n): n is string => !!n)
      ),
    [existingKbs]
  );

  const handleNext = async () => {
    try {
      const values = await form.validateFields();
      const name = values.name.trim();

      if (existingNames.has(name.toLowerCase())) {
        message.error(t("aidpKnowledge.createDuplicateName", { name }));
        return;
      }

      // Save form values before fields unmount
      setFormValues({
        name,
        description: values.description?.trim() || undefined,
        vlm_model: values.caption_enable
          ? values.vlm_model || defaultVlmModel || undefined
          : "",
        chunk_token_num:
          values.chunk_token_num ?? AIDP_CREATE_DEFAULTS.chunk_token_num,
        chunk_overlap_num:
          values.chunk_overlap_num ?? AIDP_CREATE_DEFAULTS.chunk_overlap_num,
        caption_enable: values.caption_enable ? 1 : 0,
        // The permission select is disabled at PRIVATE so users cannot pick
        // group_ids while PRIVATE; we always coerce to [] for safety.
        ingroup_permission: values.ingroup_permission ?? "READ_ONLY",
        group_ids:
          (values.ingroup_permission ?? "READ_ONLY") === "PRIVATE"
            ? []
            : Array.isArray(values.group_ids)
              ? values.group_ids
              : [],
      });
      setCurrent(1);
    } catch {
      // form validation error, do nothing
    }
  };

  const handleBack = () => {
    // Restore formValues into the Form when remounting Step 0,
    // since antd Form clears field values when the Form is unmounted.
    form.setFieldsValue(formValues);
    setCurrent(0);
  };



  const handleSubmit = async (skipUpload: boolean) => {
    try {
      if (!formValues.name?.trim()) {
        message.error(t("aidpKnowledge.kbNameRequired"));
        setCurrent(0);
        return;
      }
      setLoading(true);

      // Step 1: Create KB
      // Aligned with sdk/nexent/core/knowledge_base/mapper.py#build_create_payload
      const created = await aidpKnowledgeService.createKb({
        name: formValues.name.trim(),
        description: formValues.description || "",
        chunk_token_num: formValues.chunk_token_num,
        chunk_overlap_num: formValues.chunk_overlap_num,
        embedding_model: AIDP_CREATE_DEFAULTS.embedding_model,
        vlm_model:
          formValues.caption_enable === 1
            ? formValues.vlm_model || defaultVlmModel || ""
            : "",
        is_personal: AIDP_CREATE_DEFAULTS.is_personal,
        topk: AIDP_CREATE_DEFAULTS.topk,
        similarity: AIDP_CREATE_DEFAULTS.similarity,
        smartsplit: AIDP_CREATE_DEFAULTS.smartsplit,
        caption_enable: formValues.caption_enable,
        // v7.1: forward in-group permission + groups to the backend so the
        // knowledge-base permission row is created in lockstep with the KB.
        ingroup_permission: formValues.ingroup_permission,
        group_ids: formValues.group_ids,
      });

      // Step 2: Upload files (if any and not skipped)
      if (!skipUpload && fileList.length > 0 && created.kds_id) {
        const result = await aidpKnowledgeService.uploadDocs(
          created.kds_id,
          fileList
        );

        if (result.failed > 0 && result.success === 0) {
          message.warning(
            t("aidpKnowledge.createKbSuccess") +
              " | " +
              t("aidpKnowledge.uploadFailed")
          );
        } else if (result.failed > 0) {
          message.info(
            t("aidpKnowledge.createKbSuccess") +
              " | " +
              t("aidpKnowledge.uploadPartial", {
                success: result.success,
                failed: result.failed,
              })
          );
        } else {
          message.success(
            t("aidpKnowledge.createKbSuccess") +
              " | " +
              t("aidpKnowledge.uploadSuccess", { count: result.success })
          );
        }
      } else {
        message.success(t("aidpKnowledge.createKbSuccess"));
      }

      const newKdsId = created.kds_id;
      handleReset();
      onSuccess(newKdsId);
    } catch (error) {
      message.error(t("aidpKnowledge.createKbFailed"));
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    form.resetFields();
    setCurrent(0);
    setFileList([]);
    setFormValues({
      name: "",
      chunk_token_num: AIDP_CREATE_DEFAULTS.chunk_token_num,
      chunk_overlap_num: AIDP_CREATE_DEFAULTS.chunk_overlap_num,
      caption_enable: AIDP_CREATE_DEFAULTS.caption_enable,
      ingroup_permission: "READ_ONLY",
      group_ids: [],
    });
  };

  const handleCancel = () => {
    handleReset();
    onCancel();
  };

  // ---- Render steps ----

  const renderStep0 = () => (
    <>
      <Form form={form} layout="vertical" className="mt-4">
        <Form.Item
          name="name"
          label={t("aidpKnowledge.kbName")}
          rules={[
            { required: true, message: t("aidpKnowledge.kbNameRequired") },
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

        {/* v7.1: in-group permission controls.
            PRIVATE disallows picking groups (groups are forced to []).
            Non-PRIVATE selections REQUIRE a non-empty group_ids list. */}
        <Form.Item
          name="ingroup_permission"
          label={t("aidpKnowledge.createIngroupPermission")}
          initialValue="READ_ONLY"
          rules={[
            {
              required: true,
              message: t("aidpKnowledge.createIngroupPermissionRequired"),
            },
          ]}
        >
          <Select
            options={[
              {
                value: "EDIT",
                label: t("aidpKnowledge.createIngroupPermissionEdit"),
              },
              {
                value: "READ_ONLY",
                label: t("aidpKnowledge.createIngroupPermissionRead"),
              },
              {
                value: "PRIVATE",
                label: t("aidpKnowledge.createIngroupPermissionPrivate"),
              },
            ]}
          />
        </Form.Item>

        <Form.Item
          name="group_ids"
          label={t("aidpKnowledge.createAccessGroups")}
          dependencies={["ingroup_permission"]}
          rules={[
            ({ getFieldValue }) => ({
              validator(_rule, value) {
                const level = getFieldValue("ingroup_permission") || "READ_ONLY";
                if (level === "PRIVATE") return Promise.resolve();
                if (Array.isArray(value) && value.length > 0) {
                  return Promise.resolve();
                }
                return Promise.reject(
                  new Error(t("aidpKnowledge.createAccessGroupsRequired"))
                );
              },
            }),
          ]}
        >
          <Select
            mode="multiple"
            placeholder={t("aidpKnowledge.createAccessGroupsPlaceholder")}
            disabled={Form.useWatch("ingroup_permission", form) === "PRIVATE"}
            options={groupOptions}
          />
        </Form.Item>

        <Form.Item
          name="caption_enable"
          required
          initialValue={AIDP_CREATE_DEFAULTS.caption_enable === 1}
          valuePropName="checked"
          label={
            <Space>
              <span>{t("aidpKnowledge.createCaptionEnable")}</span>
              <Tooltip title={t("aidpKnowledge.createCaptionEnableHint")}>
                <QuestionCircleOutlined className="text-gray-400 cursor-help" />
              </Tooltip>
            </Space>
          }
        >
          <Switch />
        </Form.Item>

        {/* VLM model picker is only relevant when multimodal captioning is
            enabled. Hide the dropdown entirely when the Switch is off so
            users aren't shown an irrelevant choice, and so the backend
            receives an empty ``vlm_model`` (see handleSubmit). */}
        {captionEnabled && (
          <Form.Item
            name="vlm_model"
            label={
              <Space>
                <span>{t("aidpKnowledge.createVlmModel")}</span>
                <Tooltip title={t("aidpKnowledge.createVlmModelHint")}>
                  <QuestionCircleOutlined className="text-gray-400 cursor-help" />
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

        <Collapse
          ghost
          size="small"
          items={[
            {
              key: "chunk_config",
              label: t("aidpKnowledge.createAdvancedOptions"),
              children: (
                <>
                  <Form.Item
                    name="chunk_token_num"
                    label={t("aidpKnowledge.createChunkTokenNum")}
                    initialValue={AIDP_CREATE_DEFAULTS.chunk_token_num}
                    rules={[
                      {
                        required: true,
                        message: t("aidpKnowledge.createChunkTokenNumRequired"),
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
                    initialValue={AIDP_CREATE_DEFAULTS.chunk_overlap_num}
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
                </>
              ),
            },
          ]}
        />
      </Form>
    </>
  );

  const renderStep1 = () => (
    <div className="mt-4">
      <Dragger
        multiple
        fileList={fileList.map((f, i) => ({
          uid: `${i}-${f.name}`,
          name: f.name,
          size: f.size,
          status: "done" as const,
          originFileObj: f,
        }))}
        beforeUpload={(_file, newFiles) => {
          // Only use beforeUpload as the single state updater for file additions.
          // Returning false prevents antd's default upload behavior.
          setFileList((prev) => {
            const existing = new Set(prev.map((f) => f.name));
            const unique = (newFiles as File[]).filter(
              (f) => !existing.has(f.name)
            );
            return [...prev, ...unique];
          });
          return false;
        }}
        onRemove={(file) => {
          setFileList((prev) =>
            prev.filter((f) => f.name !== (file as any).name)
          );
        }}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">
          {t("aidpKnowledge.uploadHint")}
        </p>
        <p className="ant-upload-hint">
          {t("aidpKnowledge.uploadHintDetail")}
        </p>
      </Dragger>

      {fileList.length === 0 && (
        <div className="mt-3 text-gray-400 text-xs text-center">
          {t("aidpKnowledge.createNoFiles")}
        </div>
      )}
    </div>
  );

  const steps = [
    { title: t("aidpKnowledge.createStepInfo") },
    { title: t("aidpKnowledge.createStepUpload") },
  ];

  return (
    <Modal
      open={open}
      title={t("aidpKnowledge.createKb")}
      onCancel={handleCancel}
      centered
      width={560}
      footer={
        <div className="flex justify-between">
          <div>
            {current === 1 && (
              <Button onClick={handleBack} disabled={loading}>
                {t("aidpKnowledge.createBack")}
              </Button>
            )}
          </div>
          <Space>
            <Button onClick={handleCancel} disabled={loading}>
              {t("common.cancel")}
            </Button>
            {current === 0 && (
              <Button type="primary" onClick={handleNext}>
                {t("aidpKnowledge.createNext")}
              </Button>
            )}
            {current === 1 && fileList.length > 0 && (
              <Button
                type="primary"
                loading={loading}
                onClick={() => handleSubmit(false)}
              >
                {t("aidpKnowledge.createSubmit")}
              </Button>
            )}
            {current === 1 && (
              <Button
                type={fileList.length === 0 ? "primary" : "default"}
                loading={loading}
                onClick={() => handleSubmit(true)}
              >
                {t("aidpKnowledge.createSkipUpload")}
              </Button>
            )}
          </Space>
        </div>
      }
    >
      <Steps current={current} items={steps} size="small" className="mb-2" />
      <Divider className="my-3" />
      {current === 0 && renderStep0()}
      {current === 1 && renderStep1()}
    </Modal>
  );
};

export default AidpCreateKbModal;
