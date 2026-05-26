"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  App,
  Button,
  Card,
  Collapse,
  Flex,
  Form,
  Input,
  List,
  Modal,
  Space,
  Tag,
  Typography,
} from "antd";

import { useConfirmModal } from "@/hooks/useConfirmModal";
import log from "@/lib/logger";
import { promptTemplateService } from "@/services/promptTemplateService";
import {
  ADVANCED_PROMPT_TEMPLATE_FIELDS,
  BASIC_PROMPT_TEMPLATE_FIELDS,
  createEmptyPromptTemplateContent,
  type PromptTemplateFieldConfig,
} from "@/const/promptTemplate";
import {
  PromptTemplate,
  PromptTemplateContent,
  PromptTemplatePayload,
} from "@/types/agentConfig";

const { Text } = Typography;

type PromptTemplateFormValues = {
  template_name: string;
  description?: string;
  template_content_zh?: Partial<PromptTemplateContent>;
  template_content_en?: Partial<PromptTemplateContent>;
};

function mergeTemplateContent(
  seedContent?: Partial<PromptTemplateContent> | null,
  formContent?: Partial<PromptTemplateContent>
): PromptTemplateContent {
  const mergedContent = createEmptyPromptTemplateContent() as PromptTemplateContent;
  const keys = Object.keys(mergedContent) as Array<keyof PromptTemplateContent>;

  keys.forEach((key) => {
    const formValue = formContent?.[key];
    const seedValue = seedContent?.[key];

    mergedContent[key] =
      typeof formValue === "string"
        ? formValue
        : typeof seedValue === "string"
          ? seedValue
          : "";
  });

  return mergedContent;
}

interface PromptTemplateManagerModalProps {
  open: boolean;
  editable: boolean;
  templates: PromptTemplate[];
  selectedTemplateId: number;
  onClose: () => void;
  onSelectTemplate: (template: PromptTemplate) => void;
  onTemplatesChanged: () => void;
}

export default function PromptTemplateManagerModal({
  open,
  editable,
  templates,
  selectedTemplateId,
  onClose,
  onSelectTemplate,
  onTemplatesChanged,
}: PromptTemplateManagerModalProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { confirm } = useConfirmModal();
  const [editorForm] = Form.useForm();
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<PromptTemplate | null>(null);
  const [editorSeedTemplate, setEditorSeedTemplate] = useState<PromptTemplate | null>(null);
  const [editorReadOnly, setEditorReadOnly] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const templateOptions = templates.map((template) => ({
    value: template.template_id,
    label: template.is_system_default
      ? t("businessLogic.config.template.systemDefault")
      : template.template_name,
  }));

  const openCreateEditor = async () => {
    try {
      const systemDefault = await promptTemplateService.detail(0);
      const seedTemplate = systemDefault || templates.find((item) => item.template_id === 0) || null;
      editorForm.setFieldsValue({
        template_name: "",
        description: "",
        template_content_zh: seedTemplate?.template_content_zh || createEmptyPromptTemplateContent(),
        template_content_en: seedTemplate?.template_content_en || createEmptyPromptTemplateContent(),
      });
      setEditingTemplate(null);
      setEditorSeedTemplate(seedTemplate);
      setEditorReadOnly(false);
      setEditorOpen(true);
    } catch (error) {
      log.error("Failed to load default prompt template:", error);
      message.error(t("businessLogic.config.template.loadError"));
    }
  };

  const openTemplateEditor = (template: PromptTemplate, readOnly = false) => {
    editorForm.setFieldsValue({
      template_name: template.template_name,
      description: template.description || "",
      template_content_zh: template.template_content_zh || createEmptyPromptTemplateContent(),
      template_content_en: template.template_content_en || createEmptyPromptTemplateContent(),
    });
    setEditingTemplate(template);
    setEditorSeedTemplate(template);
    setEditorReadOnly(readOnly);
    setEditorOpen(true);
  };

  const closeEditor = () => {
    setEditorOpen(false);
    setEditingTemplate(null);
    setEditorSeedTemplate(null);
    setEditorReadOnly(false);
    editorForm.resetFields();
  };

  const buildPayload = (values: PromptTemplateFormValues): PromptTemplatePayload => {
    const templateContentZh = mergeTemplateContent(
      editorSeedTemplate?.template_content_zh,
      values.template_content_zh
    );
    const templateContentEn = mergeTemplateContent(
      editorSeedTemplate?.template_content_en,
      values.template_content_en
    );
    const hasEnglishContent = Object.values(templateContentEn).some(
      (value) => typeof value === "string" && value.trim() !== ""
    );

    return {
      template_name: values.template_name,
      description: values.description,
      template_type: "agent_generate",
      template_content_zh: templateContentZh,
      template_content_en: hasEnglishContent ? templateContentEn : null,
    };
  };

  const renderTemplateFields = (
    contentName: "template_content_zh" | "template_content_en",
    fields: readonly PromptTemplateFieldConfig[],
    required: boolean
  ) => (
    <Flex vertical gap={12}>
      {fields.map((field) => (
        <Form.Item
          key={`${contentName}-${field.key}`}
          name={[contentName, field.key]}
          label={t(field.labelKey)}
          rules={
            required
              ? [
                  {
                    required: true,
                    message: t("businessLogic.config.template.contentRequired"),
                  },
                ]
              : undefined
          }
        >
          <Input.TextArea
            rows={4}
            autoSize={{ minRows: 3, maxRows: 8 }}
            readOnly={editorReadOnly}
          />
        </Form.Item>
      ))}
    </Flex>
  );

  const renderLanguagePanel = (language: "zh" | "en") => {
    const isChinese = language === "zh";
    const contentName = isChinese ? "template_content_zh" : "template_content_en";

    return (
      <Flex vertical gap={16}>
        <Flex vertical gap={4}>
          <Text strong>{t("businessLogic.config.template.basicSection")}</Text>
          <Text type="secondary">
            {t("businessLogic.config.template.basicDescription")}
          </Text>
          {!isChinese ? (
            <Text type="secondary">
              {t("businessLogic.config.template.englishOptionalDescription")}
            </Text>
          ) : null}
        </Flex>

        {renderTemplateFields(contentName, BASIC_PROMPT_TEMPLATE_FIELDS, isChinese)}

        <Collapse
          ghost
          items={[
            {
              key: `${language}-advanced`,
              label: t("businessLogic.config.template.advancedSection"),
              children: (
                <Flex vertical gap={12}>
                  <Text type="secondary">
                    {t("businessLogic.config.template.advancedDescription")}
                  </Text>
                  {renderTemplateFields(contentName, ADVANCED_PROMPT_TEMPLATE_FIELDS, false)}
                </Flex>
              ),
            },
          ]}
        />
      </Flex>
    );
  };

  const handleSubmit = async () => {
    try {
      const values = await editorForm.validateFields();
      const payload = buildPayload(values);
      setSubmitting(true);

      const savedTemplate = editingTemplate
        ? await promptTemplateService.update(editingTemplate.template_id, payload)
        : await promptTemplateService.create(payload);

      if (savedTemplate) {
        onTemplatesChanged();
        onSelectTemplate(savedTemplate);
        message.success(t("businessLogic.config.template.saveSuccess"));
        closeEditor();
      }
    } catch (error) {
      if ((error as any)?.errorFields) {
        return;
      }
      log.error("Failed to save prompt template:", error);
      message.error(t("businessLogic.config.template.saveError"));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = (template: PromptTemplate) => {
    confirm({
      title: t("businessLogic.config.modal.deleteTitle"),
      content: t("businessLogic.config.template.deleteConfirm", {
        name: template.template_name,
      }),
      onOk: async () => {
        try {
          await promptTemplateService.remove(template.template_id);
          if (selectedTemplateId === template.template_id) {
            const systemDefaultTemplate = templates.find((item) => item.template_id === 0);
            if (systemDefaultTemplate) {
              onSelectTemplate(systemDefaultTemplate);
            }
          }
          onTemplatesChanged();
          message.success(t("businessLogic.config.template.deleteSuccess"));
        } catch (error) {
          log.error("Failed to delete prompt template:", error);
          message.error(t("businessLogic.config.template.deleteError"));
        }
      },
    });
  };

  return (
    <>
      <Modal
        open={open}
        onCancel={onClose}
        title={t("businessLogic.config.template.manage")}
        width={860}
        footer={null}
        centered
      >
        <Flex vertical gap={16}>
          <Card
            size="small"
            styles={{
              body: {
                padding: 16,
              },
            }}
          >
            <Flex
              justify="space-between"
              align="center"
              gap={12}
              wrap="wrap"
            >
              <Flex vertical gap={4} style={{ minWidth: 0, flex: 1 }}>
                <Text strong>{t("businessLogic.config.template.label")}</Text>
                <Text type="secondary">
                  {t("businessLogic.config.template.manageDescription")}
                </Text>
              </Flex>
              <Button
                type="primary"
                onClick={openCreateEditor}
                disabled={!editable}
              >
                {t("businessLogic.config.template.create")}
              </Button>
            </Flex>
          </Card>

          <Flex align="center" gap={12} wrap="wrap">
            <Text type="secondary" style={{ minWidth: 72 }}>
              {t("businessLogic.config.template.label")}:
            </Text>
            <Input
              value={
                templateOptions.find((option) => option.value === selectedTemplateId)?.label
              }
              disabled
              style={{ flex: 1, minWidth: 220 }}
            />
          </Flex>

          <List
            dataSource={templates}
            locale={{
              emptyText: t("businessLogic.config.template.empty"),
            }}
            split={false}
            renderItem={(template) => {
              const isSelected = selectedTemplateId === template.template_id;
              const isSystemDefault = template.is_system_default;
              return (
                <List.Item style={{ padding: 0, marginBottom: 12 }}>
                  <Card
                    size="small"
                    style={{
                      width: "100%",
                      borderColor: isSelected ? "#91caff" : undefined,
                      boxShadow: isSelected
                        ? "0 0 0 2px rgba(24, 144, 255, 0.08)"
                        : "none",
                    }}
                    styles={{
                      body: {
                        padding: 16,
                      },
                    }}
                  >
                    <Flex
                      justify="space-between"
                      align="flex-start"
                      gap={16}
                      wrap="wrap"
                    >
                      <Flex vertical gap={8} style={{ minWidth: 0, flex: 1 }}>
                        <Space size={8} wrap>
                          <Text strong>
                            {isSystemDefault
                              ? t("businessLogic.config.template.systemDefault")
                              : template.template_name}
                          </Text>
                          {isSystemDefault ? (
                            <Tag color="default">
                              {t("businessLogic.config.template.system")}
                            </Tag>
                          ) : null}
                          {isSelected ? (
                            <Tag color="blue">
                              {t("businessLogic.config.template.current")}
                            </Tag>
                          ) : null}
                        </Space>
                        <Text type="secondary">
                          {template.description || t("businessLogic.config.template.noDescription")}
                        </Text>
                      </Flex>

                      <Space size={8} wrap>
                        <Button
                          type={isSelected ? "default" : "primary"}
                          ghost={!isSelected}
                          disabled={isSelected}
                          onClick={() => onSelectTemplate(template)}
                        >
                          {isSelected
                            ? t("businessLogic.config.template.current")
                            : t("businessLogic.config.template.use")}
                        </Button>
                        <Button
                          onClick={() => openTemplateEditor(template, true)}
                        >
                          {t("common.preview")}
                        </Button>
                        <Button
                          disabled={!editable || isSystemDefault}
                          onClick={() => openTemplateEditor(template)}
                        >
                          {t("common.edit")}
                        </Button>
                        <Button
                          danger
                          disabled={!editable || isSystemDefault}
                          onClick={() => handleDelete(template)}
                        >
                          {t("common.delete")}
                        </Button>
                      </Space>
                    </Flex>
                  </Card>
                </List.Item>
              );
            }}
          />
        </Flex>
      </Modal>

      <Modal
        open={editorOpen}
        onCancel={closeEditor}
        onOk={editorReadOnly ? closeEditor : handleSubmit}
        confirmLoading={editorReadOnly ? false : submitting}
        title={editingTemplate
          ? editorReadOnly
            ? t("common.preview")
            : t("businessLogic.config.template.editTitle")
          : t("businessLogic.config.template.createTitle")}
        width={980}
        centered
        destroyOnClose
        okText={editorReadOnly ? t("common.close") : t("common.save")}
        cancelText={t("common.cancel")}
        cancelButtonProps={editorReadOnly ? { style: { display: "none" } } : undefined}
      >
        <Flex vertical gap={16}>
          <Card
            size="small"
            styles={{
              body: {
                padding: 16,
              },
            }}
          >
            <Text type="secondary">
              {t("businessLogic.config.template.manageDescription")}
            </Text>
          </Card>

          <Form
            form={editorForm}
            layout="vertical"
          >
            <Form.Item
              name="template_name"
              label={t("businessLogic.config.template.name")}
              rules={[
                {
                  required: true,
                  message: t("businessLogic.config.template.nameRequired"),
                },
              ]}
            >
              <Input maxLength={100} readOnly={editorReadOnly} />
            </Form.Item>

            <Form.Item
              name="description"
              label={t("businessLogic.config.template.description")}
            >
              <Input maxLength={500} readOnly={editorReadOnly} />
            </Form.Item>

            <Collapse
              defaultActiveKey={["zh"]}
              items={[
                {
                  key: "zh",
                  label: t("businessLogic.config.template.language.zh"),
                  children: renderLanguagePanel("zh"),
                },
                {
                  key: "en",
                  label: t("businessLogic.config.template.language.en"),
                  children: renderLanguagePanel("en"),
                },
              ]}
            />
          </Form>
        </Flex>
      </Modal>
    </>
  );
}
