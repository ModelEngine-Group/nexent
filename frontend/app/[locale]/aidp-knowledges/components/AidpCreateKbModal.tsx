"use client";

import React, { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  Modal,
  Form,
  Input,
  Steps,
  Upload,
  Button,
  message,
  Space,
  Divider,
} from "antd";
import { InboxOutlined } from "@ant-design/icons";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import aidpKnowledgeService from "@/services/aidpKnowledgeService";

const { Dragger } = Upload;

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
  const [formValues, setFormValues] = useState<{ name: string; description?: string; embedding_model?: string }>({ name: "" });

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
      const created = await aidpKnowledgeService.createKb(serverUrl, apiKey, {
        name: formValues.name.trim(),
        description: formValues.description,
        embedding_model: formValues.embedding_model,
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
    setFormValues({ name: "" });
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
