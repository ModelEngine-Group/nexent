"use client";

import { useEffect, useState } from "react";
import { App, Form, Input } from "antd";
import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslation } from "react-i18next";

import { StandardButton } from "@/components/common/StandardButton";
import { StandardModal } from "@/components/common/StandardModal";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { getTenantResourceLimitMessage } from "@/const/errorMessageI18n";
import {
  AGENT_NAME_MAX_LENGTH,
  createAgentNameConflictValidator,
  isValidAgentDisplayName,
} from "@/hooks/agent/useSaveGuard";
import { updateAgentInfo } from "@/services/agentConfigService";

import {
  AGENT_CREATION_TEMPLATES,
  type AgentCreationTemplate,
} from "./agentCreationTemplates";

export interface CreatedAgentResult {
  agentId: number;
  displayName: string;
}

interface CreateAgentModalProps {
  open: boolean;
  onCancel: () => void;
  onCreated: (agent: CreatedAgentResult) => void | Promise<void>;
}

interface CreateAgentFormValues {
  displayName: string;
}

const CREATE_AGENT_MODAL_MAX_HEIGHT = 572;

export default function CreateAgentModal({
  open,
  onCancel,
  onCreated,
}: CreateAgentModalProps) {
  const { t } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const { message } = App.useApp();
  const params = useParams<{ locale?: string }>();
  const [form] = Form.useForm<CreateAgentFormValues>();
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(
    null
  );
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      form.resetFields();
    }
  }, [form, open]);

  const selectedTemplate = AGENT_CREATION_TEMPLATES.find(
    (template) => template.id === selectedTemplateId
  );

  const handleSubmit = async () => {
    if (isSubmitting) return;

    try {
      const values = await form.validateFields();
      setIsSubmitting(true);

      const result = await updateAgentInfo({
        display_name: values.displayName.trim(),
        description: selectedTemplate ? t(selectedTemplate.descriptionKey) : "",
        author: user?.email || "",
        max_steps: 15,
        is_main_agent: true,
        provide_run_summary: false,
        enabled: true,
      });

      if (!result.success || !result.data?.agent_id) {
        message.error(
          getTenantResourceLimitMessage(result.error, t) ||
            result.message ||
            t("businessLogic.config.error.saveFailed")
        );
        return;
      }

      await onCreated({
        agentId: Number(result.data.agent_id),
        displayName: values.displayName.trim(),
      });
      setSelectedTemplateId(null);
    } finally {
      setIsSubmitting(false);
    }
  };

  const resetModalState = () => {
    setSelectedTemplateId(null);
    setIsSubmitting(false);
  };

  const handleCancel = () => {
    resetModalState();
    onCancel();
  };

  const handleTemplateClick = (template: AgentCreationTemplate) => {
    setSelectedTemplateId((currentId) =>
      currentId === template.id ? null : template.id
    );
  };

  const locale = params.locale || "zh";

  return (
    <StandardModal
      open={open}
      width={560}
      maxHeight={CREATE_AGENT_MODAL_MAX_HEIGHT}
      title={t("chat.agentLanding.createAgent")}
      closeLabel={t("agentConfig.createModal.close")}
      cancelText={t("common.cancel")}
      confirmText={t("common.confirm")}
      footer={null}
      bodyClassName="!overflow-hidden !pb-0"
      onOpenChange={(nextOpen) => {
        if (!nextOpen) resetModalState();
      }}
      onClose={handleCancel}
    >
      <Form
        form={form}
        layout="vertical"
        preserve={false}
        onFinish={() => void handleSubmit()}
        className="!m-0"
      >
        <div className="flex items-start gap-4">
          <Form.Item
            name="displayName"
            label={t("agent.displayName")}
            validateTrigger={["onChange", "onBlur"]}
            className="!mb-0 min-w-0 flex-1"
            rules={[
              {
                required: true,
                whitespace: true,
                message: t("agent.validation.displayNameRequired"),
              },
              {
                validator: (_, value: string) =>
                  !value || isValidAgentDisplayName(value)
                    ? Promise.resolve()
                    : Promise.reject(
                        new Error(
                          t("agent.validation.displayNameMaxLength", {
                            max: AGENT_NAME_MAX_LENGTH,
                          })
                        )
                      ),
              },
              {
                ...createAgentNameConflictValidator(t, "display_name"),
                validateTrigger: "onBlur",
              },
            ]}
          >
            <Input
              autoFocus
              maxLength={AGENT_NAME_MAX_LENGTH}
              placeholder={t("agentConfig.createModal.namePlaceholder")}
              className="!h-8 !rounded-[4px] !border-[#c9c9c9] !px-3 !py-[5px] !text-[14px] !leading-[22px] ![letter-spacing:0px]"
            />
          </Form.Item>
          <StandardButton
            variant="primary"
            htmlType="submit"
            loading={isSubmitting}
            className="!mt-[30px] !mb-0"
          >
            {t("agentConfig.createModal.submit")}
          </StandardButton>
        </div>
      </Form>

      <div className="mt-4 flex items-center gap-1 text-[14px] ![letter-spacing:0px] leading-[22px]">
        <span className="text-[#191919]">
          {t("agentConfig.createModal.template.create")}
        </span>
        <Link
          href={`/${locale}/agent-space`}
          className="inline-flex items-center gap-1 ![letter-spacing:0px] text-[#2673e5]"
        >
          {t("agentConfig.createModal.template.repository")}
          <ExternalLink aria-hidden="true" size={14} strokeWidth={1.75} />
        </Link>
      </div>

      <div
        data-template-list
        className="mt-4 min-h-0 max-h-[368px] flex-1 overflow-x-hidden overflow-y-auto"
      >
        <div className="grid grid-cols-2 gap-4">
          {AGENT_CREATION_TEMPLATES.map((template) => {
            const isSelected = selectedTemplateId === template.id;

            return (
              <button
                key={template.id}
                type="button"
                aria-pressed={isSelected}
                onClick={() => handleTemplateClick(template)}
                className={`!m-0 flex h-[112px] w-full flex-col items-start justify-start rounded-[8px] border border-solid bg-white p-3 text-left ![letter-spacing:0px] transition-colors ${
                  isSelected
                    ? "!border-[#2673e5]"
                    : "!border-[#c9c9c9] hover:!border-[#2673e5]"
                }`}
              >
                <div className="flex w-full items-center gap-2">
                  <span
                    aria-hidden="true"
                    data-template-icon
                    className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] leading-none text-white ${template.iconClassName}`}
                  >
                    ✦
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[14px] font-medium leading-[22px] text-[#191919]">
                    {t(template.titleKey)}
                  </span>
                  <span className="shrink-0 rounded-[4px] bg-[rgba(25,25,25,0.05)] px-1 text-[12px] leading-[18px] text-[#393939]">
                    {t(template.tagKey)}
                  </span>
                </div>
                <span
                  data-template-description
                  className="mt-2 line-clamp-2 w-full text-[12px] leading-[18px] text-[#777]"
                >
                  {t(template.descriptionKey)}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </StandardModal>
  );
}
