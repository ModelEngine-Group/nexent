"use client";

import { useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { App, Form } from "antd";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useAgentStore } from "@/stores/agentStore";

import AgentInfo from "./components/agent-info";
import AgentPrmopt from "./components/agent-prompt";
import AgentCapability from "./components/agent-capability";
import AgentRunPolicy from "./components/agent-run-policy";
import AgentGuide from "./components/agent-guide";
import AgentDeployment from "./components/agent-deployment";
import CollaborativeAgent, {
  CollaborativeAgentActions,
} from "./components/collaborative-agent";
import GuardrailConfigContent from "./components/agentInfo/GuardrailConfigContent";
import KnowledgeBaseConfig, {
  KnowledgeBaseConfigActions,
} from "./components/knowledge-base-config";
import {
  DEFAULT_AGENT_VERIFICATION_CONFIG,
  GuardrailConfig,
} from "@/types/agentConfig";
import { useModelList } from "@/hooks/model/useModelList";

import {
  ChevronDown,
  Info,
  Cpu,
  Wrench,
  Play,
  Globe,
  Database,
  MessageSquare,
  ShieldCheck,
} from "lucide-react";

interface ConfigSectionProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  defaultOpen?: boolean;
  headerActions?: React.ReactNode;
  children: React.ReactNode;
}

function ConfigSection({
  title,
  description,
  icon,
  defaultOpen = false,
  headerActions,
  children,
}: ConfigSectionProps) {
  return (
    <Collapsible
      defaultOpen={defaultOpen}
      className="overflow-hidden rounded-lg border border-gray-200 bg-white"
    >
      <div className="flex items-center gap-4  transition-colors hover:bg-gray-50 px-2">
        <CollapsibleTrigger className="flex min-w-0 flex-1 items-center px-2 py-4 gap-4 text-left">
          <div className="flex min-w-0 items-center gap-2">
            <ChevronDown className="h-4 w-4 text-gray-400 transition-transform group-data-[state=open]:rotate-180" />

            <div className="flex shrink-0 items-center gap-2 text-sm font-medium text-gray-900">
              {icon}
              <span>{title}</span>
            </div>
            <p className="min-w-0 truncate text-xs text-gray-500">
              {description}
            </p>
          </div>
        </CollapsibleTrigger>
        {headerActions && (
          <div className="flex shrink-0 items-center gap-2">
            {headerActions}
          </div>
        )}
      </div>
      <CollapsibleContent className="border-t border-gray-200 bg-gray-50/70 px-4 py-4">
        {children}
      </CollapsibleContent>
    </Collapsible>
  );
}

export default function AgentConfig() {
  const { t } = useTranslation("common");
  const [form] = Form.useForm();
  const isReadOnly = useAgentStore((state) => state.isReadOnly);
  const editedAgent = useAgentStore((state) => state.editedAgent);
  const flushDraft = useAgentStore((state) => state.flushDraft);
  const updateAgentConfig = useAgentStore((state) => state.updateAgentConfig);
  const { availableLlmModels } = useModelList();
  const { message } = App.useApp();
  const saveError = useAgentStore((state) => state.saveError);
  const clearSaveError = useAgentStore((state) => state.clearSaveError);
  const setSaveValidation = useAgentConfigStore(
    (state) => state.setSaveValidation
  );
  const handleTabChange = useCallback(() => {
    flushDraft();
  }, [flushDraft]);

  const handleGuardrailDraftChange = useCallback(
    (guardrailConfig: GuardrailConfig) => {
      const verificationConfig =
        useAgentStore.getState().editedAgent?.verification_config;
      if (
        JSON.stringify(verificationConfig?.guardrail_config) ===
        JSON.stringify(guardrailConfig)
      ) {
        return;
      }
      updateAgentConfig({
        verification_config: {
          ...DEFAULT_AGENT_VERIFICATION_CONFIG,
          ...verificationConfig,
          guardrail_config: guardrailConfig,
        },
      });
    },
    [updateAgentConfig]
  );

  useEffect(() => {
    if (!saveError) {
      return;
    }

    message.error(saveError);
    clearSaveError();
  }, [clearSaveError, message, saveError]);

  useEffect(() => {
    setSaveValidation(async () => {
      if (!editedAgent) {
        return;
      }

      const errors = [];

      if (!editedAgent.name.trim()) {
        errors.push({ name: "name", errors: ["请输入 Agent 名称"] });
      }
      if (
        !editedAgent.max_step ||
        editedAgent.max_step < 1 ||
        editedAgent.max_step > 1000
      ) {
        errors.push({
          name: "max_step",
          errors: ["最大运行步数必须在 1 到 1000 之间"],
        });
      }
      if (
        editedAgent.requested_output_tokens != null &&
        (editedAgent.requested_output_tokens < 128 ||
          editedAgent.requested_output_tokens > 32768)
      ) {
        errors.push({
          name: "requested_output_tokens",
          errors: ["输出 Token 数必须在 128 到 32768 之间"],
        });
      }

      if (errors.length > 0) {
        form.setFields(errors);
        throw new Error("Agent configuration validation failed");
      }

      form.setFields([
        { name: "name", errors: [] },
        { name: "max_step", errors: [] },
        { name: "requested_output_tokens", errors: [] },
      ]);
    });

    return () => setSaveValidation(null);
  }, [editedAgent, form, setSaveValidation]);

  if (!editedAgent) {
    return (
      <div className="relative flex h-full min-h-0 items-center justify-center">
        <div className="space-y-3 text-center animate-in fade-in-50 duration-400">
          <div className="flex items-center justify-center gap-3 animate-in slide-in-from-bottom-2 duration-300 delay-150">
            <Info
              className="text-gray-400 transition-all duration-300 animate-in zoom-in-75 delay-100"
              size={48}
            />
            <h3 className="text-lg font-medium text-gray-700 transition-all duration-300">
              {t("systemPrompt.nonEditing.title")}
            </h3>
          </div>
          <p className="text-sm text-gray-500 transition-all duration-300">
            {t("systemPrompt.nonEditing.subtitle")}
          </p>
        </div>
      </div>
    );
  }

  return (
    <Form
      form={form}
      layout="vertical"
      disabled={isReadOnly}
      className="flex h-full min-h-0 flex-col"
      initialValues={editedAgent}
    >
      <Tabs
        defaultValue="basic"
        onValueChange={handleTabChange}
        className="flex h-full min-h-0 flex-col"
      >
        <TabsList className="flex h-10 w-full shrink-0 items-end justify-start gap-4 rounded-none border-b border-gray-200 bg-transparent p-0">
          <TabsTrigger
            value="basic"
            className="h-10 rounded-none border-b-2 border-transparent px-0 pb-2 pt-1 text-gray-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none"
          >
            基本设置
          </TabsTrigger>
          <TabsTrigger
            value="advanced"
            className="h-10 rounded-none border-b-2 border-transparent px-0 pb-2 pt-1 text-gray-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none"
          >
            高级设置
          </TabsTrigger>
        </TabsList>

        <TabsContent
          value="basic"
          className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1 mt-3"
        >
          {/* 1. 展示信息 */}
          <ConfigSection
            title="展示信息"
            description="配置图标、展示名称、变量名、作者和简介"
            icon={<Info className="h-4 w-4 shrink-0 text-blue-500" />}
            defaultOpen
          >
            <AgentInfo />
          </ConfigSection>

          {/* 2. 角色与模型 */}
          <ConfigSection
            title="角色与模型"
            description="配置大语言模型以及智能体角色、使用要求和示例"
            icon={<Cpu className="h-4 w-4 shrink-0 text-blue-500" />}
            defaultOpen
          >
            <AgentPrmopt />
          </ConfigSection>

          {/* 3. 工具与技能 */}
          <ConfigSection
            title="工具与技能"
            description="管理 Agent 可使用的工具和技能"
            icon={<Wrench className="h-4 w-4 shrink-0 text-blue-500" />}
          >
            <AgentCapability />
          </ConfigSection>

          {/* 4. 运行策略 */}
          <ConfigSection
            title="运行策略"
            description="配置最大运行步数、输出预留、结果自验证和运行摘要"
            icon={<Play className="h-4 w-4 shrink-0 text-blue-500" />}
          >
            <AgentRunPolicy />
          </ConfigSection>

          {/* 5. 发布属性 */}
          <ConfigSection
            title="发布属性"
            description="配置用户组、组内权限、设为主智能体和 A2A 发布"
            icon={<Globe className="h-4 w-4 shrink-0 text-blue-500" />}
          >
            <AgentDeployment />
          </ConfigSection>
        </TabsContent>

        <TabsContent
          value="advanced"
          className={cn("min-h-0 flex-1 space-y-3 overflow-y-auto pr-1 mt-3")}
        >
          <ConfigSection
            title="协作智能体"
            description="添加内部或外部智能体，并配置协作关系"
            icon={<Cpu className="h-4 w-4 shrink-0 text-blue-500" />}
            headerActions={<CollaborativeAgentActions />}
          >
            <CollaborativeAgent />
          </ConfigSection>

          <ConfigSection
            title="知识库"
            description="选择知识库后自动启用知识库检索能力并建立关联"
            icon={<Database className="h-4 w-4 shrink-0 text-blue-500" />}
            headerActions={<KnowledgeBaseConfigActions />}
          >
            <KnowledgeBaseConfig />
          </ConfigSection>

          <ConfigSection
            title="会话引导"
            description="配置用户首次进入会话时的开场白和示例问题"
            icon={<MessageSquare className="h-4 w-4 shrink-0 text-blue-500" />}
          >
            <AgentGuide />
          </ConfigSection>

          <ConfigSection
            title="安全护栏"
            description="配置内容匹配规则、处理动作和规则测试"
            icon={<ShieldCheck className="h-4 w-4 shrink-0 text-blue-500" />}
          >
            <GuardrailConfigContent
              config={
                editedAgent.verification_config?.guardrail_config ||
                DEFAULT_AGENT_VERIFICATION_CONFIG.guardrail_config!
              }
              llmModels={availableLlmModels}
              defaultModelId={editedAgent.model_ids?.[0]}
              onDraftChange={handleGuardrailDraftChange}
            />
          </ConfigSection>
        </TabsContent>
      </Tabs>
    </Form>
  );
}
