"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Form } from "antd";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
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
import GuardrailConfigContent, {
  GuardrailConfigActions,
} from "./components/advanced/GuardrailConfigContent";
import KnowledgeBaseConfig, {
  KnowledgeBaseConfigActions,
} from "./components/knowledge-base-search";
import AgentVersionPubulishModal from "./versions/AgentVersionPubulishModal";

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
  Bug,
  Rocket,
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

interface AgentConfigProps {
  isDebugVisible: boolean;
  onToggleDebug: () => void;
}

export default function AgentConfig({
  isDebugVisible,
  onToggleDebug,
}: AgentConfigProps) {
  const { t } = useTranslation("common");
  const [form] = Form.useForm();
  const [isPublishModalOpen, setIsPublishModalOpen] = useState(false);

  const isReadOnly = useAgentStore((state) => state.isReadOnly);
  const agentId = useAgentStore((state) => state.agentId);
  const editedAgent = useAgentStore((state) => state.editedAgent);
  const flushDraft = useAgentStore((state) => state.flushDraft);
  const { message } = App.useApp();
  const saveError = useAgentStore((state) => state.saveError);
  const clearSaveError = useAgentStore((state) => state.clearSaveError);
  const initializedAgentIdRef = useRef<number | null>(null);

  useEffect(() => {
    if (agentId === initializedAgentIdRef.current) {
      return;
    }

    initializedAgentIdRef.current = agentId;
    form.resetFields();
    if (editedAgent) {
      form.setFieldsValue(editedAgent);
    }
  }, [agentId, editedAgent, form]);

  const handleTabChange = useCallback(() => {
    flushDraft();
  }, [flushDraft]);

  const handlePublish = async () => {
    try {
      await form.validateFields();
      setIsPublishModalOpen(true);
    } catch {
      // Field validation errors are rendered by Ant Design.
    }
  };

  useEffect(() => {
    if (!saveError) {
      return;
    }

    message.error(saveError);
    clearSaveError();
  }, [clearSaveError, message, saveError]);

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
    >
      <Tabs
        defaultValue="basic"
        onValueChange={handleTabChange}
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList className="flex h-10 w-full shrink-0 items-end justify-start gap-4 rounded-none border-b border-gray-200 bg-transparent p-0">
          <TabsTrigger
            value="basic"
            className="h-10 rounded-none border-b-2 border-transparent px-0 pb-2 pt-1 text-gray-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none"
          >
            {t("agent.config.tab.basic")}
          </TabsTrigger>
          <TabsTrigger
            value="advanced"
            className="h-10 rounded-none border-b-2 border-transparent px-0 pb-2 pt-1 text-gray-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none"
          >
            {t("agent.config.tab.advanced")}
          </TabsTrigger>
        </TabsList>

        <TabsContent
          value="basic"
          className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1 mt-3"
        >
          {/* 1. 展示信息 */}
          <ConfigSection
            title={t("agent.config.section.displayInfo.title")}
            description={t("agent.config.section.displayInfo.description")}
            icon={<Info className="h-4 w-4 shrink-0 text-blue-500" />}
            defaultOpen
          >
            <AgentInfo />
          </ConfigSection>

          {/* 2. 角色与模型 */}
          <ConfigSection
            title={t("agent.config.section.roleModel.title")}
            description={t("agent.config.section.roleModel.description")}
            icon={<Cpu className="h-4 w-4 shrink-0 text-blue-500" />}
            defaultOpen
          >
            <AgentPrmopt />
          </ConfigSection>

          {/* 3. 工具与技能 */}
          <ConfigSection
            title={t("agent.config.section.toolsSkills.title")}
            description={t("agent.config.section.toolsSkills.description")}
            icon={<Wrench className="h-4 w-4 shrink-0 text-blue-500" />}
          >
            <AgentCapability />
          </ConfigSection>

          {/* 4. 运行策略 */}
          <ConfigSection
            title={t("agent.config.section.runStrategy.title")}
            description={t("agent.config.section.runStrategy.description")}
            icon={<Play className="h-4 w-4 shrink-0 text-blue-500" />}
          >
            <AgentRunPolicy />
          </ConfigSection>

          {/* 5. 发布属性 */}
          <ConfigSection
            title={t("agent.config.section.publishAttributes.title")}
            description={t("agent.config.section.publishAttributes.description")}
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
            title={t("agent.config.section.collaborativeAgents.title")}
            description={t("agent.config.section.collaborativeAgents.description")}
            icon={<Cpu className="h-4 w-4 shrink-0 text-blue-500" />}
            headerActions={<CollaborativeAgentActions />}
          >
            <CollaborativeAgent />
          </ConfigSection>

          <ConfigSection
            title={t("agent.config.section.knowledgeBase.title")}
            description={t("agent.config.section.knowledgeBase.description")}
            icon={<Database className="h-4 w-4 shrink-0 text-blue-500" />}
            headerActions={<KnowledgeBaseConfigActions />}
          >
            <KnowledgeBaseConfig />
          </ConfigSection>

          <ConfigSection
            title={t("agent.config.section.conversationGuide.title")}
            description={t("agent.config.section.conversationGuide.description")}
            icon={<MessageSquare className="h-4 w-4 shrink-0 text-blue-500" />}
          >
            <AgentGuide />
          </ConfigSection>

          <ConfigSection
            title={t("agent.config.section.guardrail.title")}
            description={t("agent.config.section.guardrail.description")}
            icon={<ShieldCheck className="h-4 w-4 shrink-0 text-blue-500" />}
            headerActions={<GuardrailConfigActions />}
          >
            <GuardrailConfigContent />
          </ConfigSection>
        </TabsContent>
      </Tabs>
      <div className="flex shrink-0 justify-end gap-2 border-t border-gray-200 bg-white pt-3 pb-1">
        <Button
          icon={<Bug size={16} />}
          disabled={agentId === null}
          onClick={onToggleDebug}
          variant="solid"
          type="primary"
        >
          {t("agent.config.button.debug")}
        </Button>
        <Button
          icon={<Rocket size={16} />}
          disabled={agentId === null || isReadOnly}
          onClick={handlePublish}
          color="green"
          variant="solid"
        >
          {t("agent.config.button.publish")}
        </Button>
      </div>
      <AgentVersionPubulishModal
        open={isPublishModalOpen}
        onClose={() => setIsPublishModalOpen(false)}
        agentId={agentId}
      />
    </Form>
  );
}
