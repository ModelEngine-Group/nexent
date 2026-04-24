"use client";

import { useEffect, useMemo, useState } from "react";
import { App, Button, Form, Input, Modal, Popconfirm, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useTranslation } from "react-i18next";

import type { PromptTemplateItem } from "@/types/agentConfig";
import {
  createPromptTemplate,
  deletePromptTemplate,
  updatePromptTemplate,
} from "@/services/promptService";

interface PromptTemplateManageModalProps {
  open: boolean;
  templates: PromptTemplateItem[];
  onClose: () => void;
  onRefresh: () => Promise<void>;
}

interface EditState {
  mode: "create" | "edit";
  template?: PromptTemplateItem;
}

export default function PromptTemplateManageModal({
  open,
  templates,
  onClose,
  onRefresh,
}: PromptTemplateManageModalProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [editState, setEditState] = useState<EditState | null>(null);

  useEffect(() => {
    if (!editState) {
      form.resetFields();
      return;
    }

    form.setFieldsValue({
      name: editState.template?.name || "",
      description: editState.template?.description || "",
      content_zh: editState.template?.content_zh || "",
      content_en: editState.template?.content_en || "",
    });
  }, [editState, form]);

  const columns: ColumnsType<PromptTemplateItem> = useMemo(() => ([
    {
      title: t("businessLogic.template.manage.columns.name"),
      dataIndex: "name",
      key: "name",
      ellipsis: true,
    },
    {
      title: t("businessLogic.template.manage.columns.source"),
      dataIndex: "source",
      key: "source",
      width: 120,
      render: (value?: string) => (
        <Tag color={value === "builtin" ? "blue" : "default"}>
          {value === "builtin"
            ? t("businessLogic.template.manage.source.builtin")
            : t("businessLogic.template.manage.source.custom")}
        </Tag>
      ),
    },
    {
      title: t("businessLogic.template.manage.columns.actions"),
      key: "actions",
      width: 180,
      render: (_, record) => {
        const isBuiltin = record.source === "builtin";
        return (
        <Space size="small">
          <Button
            size="small"
            disabled={isBuiltin}
            title={isBuiltin ? t("businessLogic.template.manage.builtinReadonly") : undefined}
            onClick={() => setEditState({ mode: "edit", template: record })}
          >
            {t("common.edit")}
          </Button>
          <Popconfirm
            title={t("businessLogic.template.manage.deleteConfirm")}
            onConfirm={async () => {
              try {
                await deletePromptTemplate(record.template_id);
                message.success(t("businessLogic.template.manage.deleteSuccess"));
                await onRefresh();
              } catch (error) {
                message.error(error instanceof Error ? error.message : t("businessLogic.template.manage.deleteError"));
              }
            }}
            disabled={isBuiltin}
          >
            <Button
              size="small"
              danger
              disabled={isBuiltin}
              title={isBuiltin ? t("businessLogic.template.manage.builtinReadonly") : undefined}
            >
              {t("common.delete")}
            </Button>
          </Popconfirm>
        </Space>
        );
      },
    },
  ]), [message, onRefresh, t]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      if (editState?.mode === "edit" && editState.template) {
        await updatePromptTemplate(editState.template.template_id, values);
      } else {
        await createPromptTemplate(values);
      }
      message.success(t("businessLogic.template.manage.saveSuccess"));
      setEditState(null);
      await onRefresh();
    } catch (error) {
      if (error && typeof error === "object" && "errorFields" in error) {
        return;
      }
      message.error(error instanceof Error ? error.message : t("businessLogic.template.manage.saveError"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Modal
        open={open}
        title={t("businessLogic.template.manage.title")}
        onCancel={onClose}
        footer={[
          <Button key="add" type="primary" onClick={() => setEditState({ mode: "create" })}>
            {t("businessLogic.template.manage.add")}
          </Button>,
          <Button key="close" onClick={onClose}>
            {t("common.cancel")}
          </Button>,
        ]}
        width={900}
      >
        <Table<PromptTemplateItem>
          rowKey="template_id"
          dataSource={templates}
          columns={columns}
          pagination={{ pageSize: 5 }}
        />
      </Modal>

      <Modal
        open={!!editState}
        title={
          editState?.mode === "edit"
            ? t("businessLogic.template.manage.editTitle")
            : t("businessLogic.template.manage.createTitle")
        }
        onCancel={() => setEditState(null)}
        onOk={handleSave}
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
        confirmLoading={saving}
        width={860}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label={t("businessLogic.template.manage.form.name")}
            rules={[{ required: true, message: t("businessLogic.template.manage.form.nameRequired") }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="description"
            label={t("businessLogic.template.manage.form.description")}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="content_zh"
            label={t("businessLogic.template.manage.form.contentZh")}
            rules={[{ required: true, message: t("businessLogic.template.manage.form.contentRequired") }]}
          >
            <Input.TextArea rows={12} />
          </Form.Item>
          <Form.Item
            name="content_en"
            label={t("businessLogic.template.manage.form.contentEn")}
            extra={t("businessLogic.template.manage.form.contentEnOptional")}
          >
            <Input.TextArea rows={12} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
