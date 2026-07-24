import React, { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { Modal, Form, Input, message } from "antd";

import type { AidpKnowledgeBaseItem } from "@/types/agentConfig";
import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";

interface AidpUpdateKbModalProps {
  open: boolean;
  knowledgeBase: AidpKnowledgeBaseItem | null;
  onCancel: () => void;
  onSuccess: () => void;
}

const AidpUpdateKbModal: React.FC<AidpUpdateKbModalProps> = ({
  open,
  knowledgeBase,
  onCancel,
  onSuccess,
}) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [loading, setLoading] = React.useState(false);

  // Pre-fill form when opening
  useEffect(() => {
    if (open && knowledgeBase) {
      form.setFieldsValue({
        name: knowledgeBase.kds_name,
        description: knowledgeBase.description || "",
      });
    }
  }, [open, knowledgeBase, form]);

  const handleOk = async () => {
    if (!knowledgeBase) return;

    try {
      const values = await form.validateFields();
      setLoading(true);

      await aidpKnowledgeService.updateKb(knowledgeBase.kds_id, {
        name: values.name.trim(),
        description: values.description?.trim() || "",
      });

      message.success(t("aidpKnowledge.updateKbSuccess"));
      form.resetFields();
      onSuccess();
    } catch (error) {
      if (error && typeof error === "object" && "errorFields" in error) {
        return;
      }
      message.error(t("aidpKnowledge.updateKbFailed"));
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = () => {
    form.resetFields();
    onCancel();
  };

  return (
    <Modal
      open={open}
      title={t("aidpKnowledge.updateKb")}
      onOk={handleOk}
      onCancel={handleCancel}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      confirmLoading={loading}
      centered
      destroyOnHidden
    >
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
      </Form>
    </Modal>
  );
};

export default AidpUpdateKbModal;
