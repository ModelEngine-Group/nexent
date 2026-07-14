"use client";

import React, { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";

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
} from "antd";
import { InboxOutlined } from "@ant-design/icons";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";

const { Dragger } = Upload;

/**
 * Default AIDP knowledge base configuration.
 * Aligned with sdk/nexent/core/knowledge_base/config.py (build_create_payload defaults).
 *
 * Required fields per AIDP schema:
 *   chunk_token_num (> 0), chunk_overlap_num (>= 0)
 * Reference fills the rest (vlm_model, is_personal, topk, similarity, smartsplit, caption_enable)
 * so the backend can pass them through unchanged.
 */
const AIDP_CREATE_DEFAULTS = {
  chunk_token_num: 1024,
  chunk_overlap_num: 128,
  embedding_model: "default",
  vlm_model: "",
  is_personal: "0",
  topk: 10,
  similarity: 0.0,
  smartsplit: 1,
  caption_enable: 0,
};

interface AidpCreateKbModalProps {
  open: boolean;
  serverUrl: string;
  apiKey: string;
  existingKbs: AidpKnowledgeBaseItem[];
  onCancel: () => void;
  onSuccess: () => void;
}

const AidpCreateKbModal: React.FC<AidpCreateKbModalProps> = ({
  open,
  serverUrl,
  apiKey,
  existingKbs,
  onCancel,
  onSuccess,
}) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [current, setCurrent] = useState(0);
  const [loading, setLoading] = useState(false);
  const [fileList, setFileList] = useState<File[]>([]);
  const [formValues, setFormValues] = useState<{
    name: string;
    description?: string;
    embedding_model?: string;
    chunk_token_num: number;
    chunk_overlap_num: number;
  }>({
    name: "",
    chunk_token_num: AIDP_CREATE_DEFAULTS.chunk_token_num,
    chunk_overlap_num: AIDP_CREATE_DEFAULTS.chunk_overlap_num,
  });

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
        embedding_model: values.embedding_model?.trim() || undefined,
        // AIDP requires these chunk fields; fall back to defaults if missing.
        chunk_token_num:
          values.chunk_token_num ?? AIDP_CREATE_DEFAULTS.chunk_token_num,
        chunk_overlap_num:
          values.chunk_overlap_num ?? AIDP_CREATE_DEFAULTS.chunk_overlap_num,
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
      const created = await aidpKnowledgeService.createKb(serverUrl, apiKey, {
        name: formValues.name.trim(),
        description: formValues.description || "",
        chunk_token_num: String(formValues.chunk_token_num),
        chunk_overlap_num: String(formValues.chunk_overlap_num),
        embedding_model:
          formValues.embedding_model || AIDP_CREATE_DEFAULTS.embedding_model,
        vlm_model: AIDP_CREATE_DEFAULTS.vlm_model,
        is_personal: AIDP_CREATE_DEFAULTS.is_personal,
        topk: AIDP_CREATE_DEFAULTS.topk,
        similarity: AIDP_CREATE_DEFAULTS.similarity,
        smartsplit: AIDP_CREATE_DEFAULTS.smartsplit,
        caption_enable: AIDP_CREATE_DEFAULTS.caption_enable,
      });

      // Step 2: Upload files (if any and not skipped)
      if (!skipUpload && fileList.length > 0 && created.kds_id) {
        const result = await aidpKnowledgeService.uploadDocs(
          serverUrl,
          apiKey,
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

      handleReset();
      onSuccess();
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
        <Form.Item
          name="embedding_model"
          label={t("aidpKnowledge.embeddingModel")}
        >
          <Input placeholder={t("aidpKnowledge.embeddingModelPlaceholder")} />
        </Form.Item>

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
