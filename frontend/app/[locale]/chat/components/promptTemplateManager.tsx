"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  App,
  Button,
  Drawer,
  Form,
  Input,
  Modal,
  Space,
  Table,
  Tag,
} from "antd";
import { Plus, Pencil, Trash2, Search } from "lucide-react";

import type { ColumnsType } from "antd/es/table";
import type {
  PromptTemplate,
  PromptTemplateCreateRequest,
  PromptTemplateUpdateRequest,
} from "@/types/promptTemplate";
import {
  listPromptTemplates,
  createPromptTemplate,
  updatePromptTemplate,
  deletePromptTemplate,
} from "@/services/promptTemplateService";

interface PromptTemplateManagerProps {
  open: boolean;
  onClose: () => void;
  onApplyTemplate?: (promptText: string) => void;
}

const { TextArea } = Input;

export default function PromptTemplateManager({
  open,
  onClose,
  onApplyTemplate,
}: PromptTemplateManagerProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<PromptTemplate | null>(
    null
  );
  const [form] = Form.useForm();

  const fetchTemplates = useCallback(
    async (searchKeyword?: string) => {
      setLoading(true);
      try {
        const res = await listPromptTemplates(searchKeyword);
        setTemplates(res?.data || []);
      } catch (error) {
        message.error(t("promptTemplate.message.loadError"));
      } finally {
        setLoading(false);
      }
    },
    [message, t]
  );

  useEffect(() => {
    if (!open) return;
    fetchTemplates(keyword);
  }, [open, fetchTemplates, keyword]);

  useEffect(() => {
    if (!open) return;
    const timer = setTimeout(() => {
      fetchTemplates(keyword);
    }, 300);
    return () => clearTimeout(timer);
  }, [keyword, open, fetchTemplates]);

  const handleOpenCreate = () => {
    setEditingTemplate(null);
    form.resetFields();
    setModalOpen(true);
  };

  const handleOpenEdit = (template: PromptTemplate) => {
    setEditingTemplate(template);
    form.setFieldsValue({
      name: template.name,
      description: template.description || "",
      prompt_text: template.prompt_text,
    });
    setModalOpen(true);
  };

  const handleDelete = (template: PromptTemplate) => {
    Modal.confirm({
      title: t("promptTemplate.confirmDeleteTitle"),
      content: t("promptTemplate.confirmDeleteContent", {
        name: template.name,
      }),
      okText: t("common.delete", "Delete"),
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deletePromptTemplate({ template_id: template.template_id });
          message.success(t("promptTemplate.message.deleteSuccess"));
          fetchTemplates(keyword);
        } catch (error) {
          message.error(t("promptTemplate.message.deleteError"));
        }
      },
    });
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      if (editingTemplate) {
        const payload: PromptTemplateUpdateRequest = {
          template_id: editingTemplate.template_id,
          name: values.name,
          description: values.description,
          prompt_text: values.prompt_text,
        };
        await updatePromptTemplate(payload);
        message.success(t("promptTemplate.message.updateSuccess"));
      } else {
        const payload: PromptTemplateCreateRequest = {
          name: values.name,
          description: values.description,
          prompt_text: values.prompt_text,
        };
        await createPromptTemplate(payload);
        message.success(t("promptTemplate.message.createSuccess"));
      }
      setModalOpen(false);
      fetchTemplates(keyword);
    } catch (error) {
      if ((error as any)?.errorFields) return;
      message.error(t("promptTemplate.message.saveError"));
    }
  };

  const columns: ColumnsType<PromptTemplate> = useMemo(
    () => [
      {
        title: t("promptTemplate.table.name"),
        dataIndex: "name",
        key: "name",
        width: 180,
        render: (value, record) => (
          <Space size={6}>
            <span className="font-medium">{value}</span>
            {record.is_builtin ? (
              <Tag color="blue">{t("promptTemplate.builtin")}</Tag>
            ) : null}
          </Space>
        ),
      },
      {
        title: t("promptTemplate.table.description"),
        dataIndex: "description",
        key: "description",
        ellipsis: true,
      },
      {
        title: t("promptTemplate.table.actions"),
        key: "actions",
        width: 160,
        render: (_, record) => (
          <Space>
            <Button
              size="small"
              onClick={() => {
                onApplyTemplate?.(record.prompt_text);
                onClose();
              }}
            >
              {t("promptTemplate.use")}
            </Button>
            <Button
              size="small"
              icon={<Pencil size={14} />}
              onClick={() => handleOpenEdit(record)}
            >
              {t("common.edit", "Edit")}
            </Button>
            <Button
              size="small"
              danger
              icon={<Trash2 size={14} />}
              onClick={() => handleDelete(record)}
              disabled={record.is_builtin}
            >
              {t("common.delete", "Delete")}
            </Button>
          </Space>
        ),
      },
    ],
    [t]
  );

  return (
    <Drawer
      title={t("promptTemplate.managerTitle")}
      open={open}
      onClose={onClose}
      width={900}
      destroyOnClose
      extra={
        <Button type="primary" icon={<Plus size={16} />} onClick={handleOpenCreate}>
          {t("promptTemplate.create")}
        </Button>
      }
    >
      <div className="flex items-center gap-2 mb-4">
        <Input
          allowClear
          prefix={<Search size={16} />}
          placeholder={t("promptTemplate.searchPlaceholder")}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
      </div>

      <Table
        rowKey="template_id"
        columns={columns}
        dataSource={templates}
        loading={loading}
        pagination={{ pageSize: 8 }}
      />

      <Modal
        title={
          editingTemplate
            ? t("promptTemplate.editTitle")
            : t("promptTemplate.createTitle")
        }
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSubmit}
        okText={t("common.save", "Save")}
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            label={t("promptTemplate.form.name")}
            name="name"
            rules={[
              { required: true, message: t("promptTemplate.form.nameRequired") },
            ]}
          >
            <Input placeholder={t("promptTemplate.form.namePlaceholder")} />
          </Form.Item>
          <Form.Item
            label={t("promptTemplate.form.description")}
            name="description"
          >
            <Input placeholder={t("promptTemplate.form.descriptionPlaceholder")} />
          </Form.Item>
          <Form.Item
            label={t("promptTemplate.form.promptText")}
            name="prompt_text"
            rules={[
              {
                required: true,
                message: t("promptTemplate.form.promptTextRequired"),
              },
            ]}
          >
            <TextArea
              rows={10}
              placeholder={t("promptTemplate.form.promptTextPlaceholder")}
            />
          </Form.Item>
        </Form>
      </Modal>
    </Drawer>
  );
}
