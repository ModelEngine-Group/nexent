"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Alert, Button, Form, Tooltip } from "antd";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { useAgentStore } from "@/stores/agentStore";
import { searchAgentInfo } from "@/services/agentConfigService";
import { getUnavailableReasonLabels } from "@/lib/agentLabelMapper";
import { useSaveGuard } from "@/hooks/agent/useSaveGuard";
import { useAgentReadOnly } from "@/hooks/agent/useAgentReadOnly";
import { useNl2AgentFlow } from "@/contexts/nl2AgentFlow";

import AgentInfo from "./components/agent-info";
import AgentPrmopt from "./components/agent-prompt";
import {
  AgentSkillCapability,
  AgentToolCapability,
} from "./components/agent-capability";
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
  ChevronRight,
  Info,
  Cpu,
  Wrench,
  BlocksIcon,
  Play,
  Globe,
  Database,
  MessageSquare,
  ShieldCheck,
  Bug,
  LockOpen,
  Rocket,
  RefreshCw,
} from "lucide-react";

type AgentConfigTab = "basic" | "tools_skills" | "advanced";
type ConfigSectionKey =
  | "display_info"
  | "role_model"
  | "tools"
  | "skills"
  | "run_strategy"
  | "publish_attributes"
  | "collaborative_agents"
  | "knowledge_base"
  | "conversation_guide"
  | "guardrail";

const BASIC_CONFIG_SECTIONS = new Set<ConfigSectionKey>([
  "display_info",
  "role_model",
  "knowledge_base",
  "conversation_guide",
]);

const DEFAULT_OPEN_SECTIONS: Record<ConfigSectionKey, boolean> = {
  display_info: true,
  role_model: true,
  tools: true,
  skills: true,
  run_strategy: false,
  publish_attributes: false,
  collaborative_agents: false,
  knowledge_base: false,
  conversation_guide: false,
  guardrail: false,
};

interface ConfigSectionProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  containerRef?: React.Ref<HTMLDivElement>;
  headerActions?: React.ReactNode;
  children: React.ReactNode;
}

function ConfigSection({
  title,
  description,
  icon,
  open,
  onOpenChange,
  containerRef,
  headerActions,
  children,
}: ConfigSectionProps) {
  return (
    <div ref={containerRef}>
      <Collapsible
        open={open}
        onOpenChange={onOpenChange}
        className="overflow-hidden rounded-lg border border-gray-200 bg-white"
      >
        <div className="flex items-center gap-4  transition-colors hover:bg-gray-50 px-2">
          <CollapsibleTrigger className="group flex min-w-0 flex-1 cursor-pointer select-none items-center px-2 py-4 gap-4 text-left">
            <div className="flex min-w-0 items-center gap-2">
              <ChevronRight className="h-4 w-4 text-gray-400 transition-transform group-data-[state=open]:rotate-90" />

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
    </div>
  );
}

interface AgentConfigProps {
  canManualUnlock: boolean;
  onManualUnlock: () => void;
  onToggleDebug: () => void;
  actionAreaRef?: React.Ref<HTMLDivElement>;
  onPublished?: () => void;
}

export default function AgentConfig({
  canManualUnlock,
  onManualUnlock,
  onToggleDebug,
  actionAreaRef,
  onPublished,
}: AgentConfigProps) {
  const { t } = useTranslation("common");
  const [form] = Form.useForm();
  const [isPublishModalOpen, setIsPublishModalOpen] = useState(false);
  const [isRefreshingAvailability, setIsRefreshingAvailability] = useState(false);
  const [activeConfigTab, setActiveConfigTab] =
    useState<AgentConfigTab>("basic");
  const [openSections, setOpenSections] = useState<
    Record<ConfigSectionKey, boolean>
  >(() => ({ ...DEFAULT_OPEN_SECTIONS }));
  const displayInfoSectionRef = useRef<HTMLDivElement>(null);
  const roleModelSectionRef = useRef<HTMLDivElement>(null);
  const toolsSectionRef = useRef<HTMLDivElement>(null);
  const skillsSectionRef = useRef<HTMLDivElement>(null);
  const runStrategySectionRef = useRef<HTMLDivElement>(null);
  const publishAttributesSectionRef = useRef<HTMLDivElement>(null);
  const collaborativeAgentsSectionRef = useRef<HTMLDivElement>(null);
  const knowledgeBaseSectionRef = useRef<HTMLDivElement>(null);
  const conversationGuideSectionRef = useRef<HTMLDivElement>(null);
  const guardrailSectionRef = useRef<HTMLDivElement>(null);
  const lastScrolledRequestRef = useRef<string | null>(null);
  const { configFocusRequest, clearConfigFocusRequest } = useNl2AgentFlow();

  const isReadOnly = useAgentReadOnly();
  const agentId = useAgentStore((state) => state.agentId);
  const editedAgent = useAgentStore((state) => state.editedAgent);
  const unavailableReasonLabels = getUnavailableReasonLabels(
    Array.isArray(editedAgent?.unavailable_reasons)
      ? editedAgent.unavailable_reasons.filter(Boolean)
      : [],
    t
  );
  const serverSnapshotRevision = useAgentStore(
    (state) => state.serverSnapshotRevision
  );
  const flushDraft = useAgentStore((state) => state.flushDraft);
  const { save } = useSaveGuard();
  const { message } = App.useApp();
  const saveError = useAgentStore((state) => state.saveError);
  const clearSaveError = useAgentStore((state) => state.clearSaveError);
  const replaceServerSnapshot = useAgentStore((state) => state.replaceServerSnapshot);

  const handleRefreshAvailability = useCallback(async () => {
    if (!agentId || isRefreshingAvailability) return;
    setIsRefreshingAvailability(true);
    try {
      const result = await searchAgentInfo(agentId);
      if (result.success && result.data) {
        replaceServerSnapshot(agentId, result.data);
      } else {
        message.error(result.message || t("agent.config.refreshAvailabilityFailed"));
      }
    } catch {
      message.error(t("agent.config.refreshAvailabilityFailed"));
    } finally {
      setIsRefreshingAvailability(false);
    }
  }, [agentId, isRefreshingAvailability, message, replaceServerSnapshot, t]);

  useEffect(() => {
    setActiveConfigTab("basic");
    setOpenSections({ ...DEFAULT_OPEN_SECTIONS });
    lastScrolledRequestRef.current = null;
  }, [agentId]);

  useEffect(() => {
    form.resetFields();
    const serverSnapshot = useAgentStore.getState().editedAgent;
    if (serverSnapshot) {
      form.setFieldsValue(serverSnapshot);
    }
  }, [agentId, form, serverSnapshotRevision]);

  useEffect(() => {
    if (!configFocusRequest || configFocusRequest.agentId !== agentId) return;

    const { requestId, target } = configFocusRequest;
    const requestKey = `${configFocusRequest.agentId}:${requestId}`;
    if (lastScrolledRequestRef.current === requestKey) {
      return;
    }
    const targetSection: ConfigSectionKey =
      target.section === "tools_skills" ? target.capabilityTab : target.section;
    const newTab = BASIC_CONFIG_SECTIONS.has(targetSection)
      ? "basic"
      : target.section === "tools_skills"
        ? "tools_skills"
        : "advanced";
    setActiveConfigTab(newTab);
    setOpenSections((current) =>
      current[targetSection] ? current : { ...current, [targetSection]: true }
    );

    lastScrolledRequestRef.current = requestKey;
    const frameId = window.requestAnimationFrame(() => {
      const sectionRefs: Record<ConfigSectionKey, React.RefObject<HTMLDivElement | null>> = {
        display_info: displayInfoSectionRef,
        role_model: roleModelSectionRef,
        tools: toolsSectionRef,
        skills: skillsSectionRef,
        run_strategy: runStrategySectionRef,
        publish_attributes: publishAttributesSectionRef,
        collaborative_agents: collaborativeAgentsSectionRef,
        knowledge_base: knowledgeBaseSectionRef,
        conversation_guide: conversationGuideSectionRef,
        guardrail: guardrailSectionRef,
      };
      const sectionElement = sectionRefs[targetSection].current;
      if (!sectionElement) {
        clearConfigFocusRequest();
        return;
      }

      const prefersReducedMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)"
      ).matches;
      sectionElement.scrollIntoView({
        behavior: prefersReducedMotion ? "auto" : "smooth",
        block: "nearest",
      });
      clearConfigFocusRequest();
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [agentId, configFocusRequest, clearConfigFocusRequest]);

  const handleTabChange = useCallback(
    (value: string) => {
      flushDraft();
      if (
        value === "basic" ||
        value === "tools_skills" ||
        value === "advanced"
      ) {
        setActiveConfigTab(value);
      }
    },
    [flushDraft]
  );

  const handleSectionOpenChange = useCallback(
    (section: ConfigSectionKey, open: boolean) => {
      setOpenSections((current) =>
        current[section] === open ? current : { ...current, [section]: open }
      );
    },
    []
  );

  const handleDebug = async () => {
    try {
      await form.validateFields();
      if (!(await save())) return;
      onToggleDebug();
    } catch {
      // Field validation errors are rendered by Ant Design.
    }
  };

  const handlePublish = async () => {
    try {
      await form.validateFields();
      if (!(await save())) return;
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
        value={activeConfigTab}
        onValueChange={handleTabChange}
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList className="relative z-20 flex h-10 w-full shrink-0 items-end justify-start gap-4 rounded-none border-b border-gray-200 bg-transparent p-0">
          <TabsTrigger
            value="basic"
            className="h-10 rounded-none border-b-2 border-transparent px-0 pb-2 pt-1 text-gray-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none"
          >
            {t("agent.config.tab.basic")}
          </TabsTrigger>
          <TabsTrigger
            value="tools_skills"
            className="h-10 rounded-none border-b-2 border-transparent px-0 pb-2 pt-1 text-gray-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none"
          >
            {t("agent.config.tab.toolsSkills")}
          </TabsTrigger>
          <TabsTrigger
            value="advanced"
            className="h-10 rounded-none border-b-2 border-transparent px-0 pb-2 pt-1 text-gray-500 shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none"
          >
            {t("agent.config.tab.advanced")}
          </TabsTrigger>
        </TabsList>
        <div className="mt-2">
          {unavailableReasonLabels.length > 0 && (
            <Alert
              className="mt-2"
              type="warning"
              showIcon
              title={
                <div className="">
                  <span className="flex justify-between items-center gap-2">
                    <span>{`${t("agent.unavailable")}${unavailableReasonLabels.join("、")}`}</span>
                    <Button
                      type="link"
                      size="small"
                      icon={<RefreshCw size={12} className={isRefreshingAvailability ? "animate-spin" : ""} />}
                      onClick={handleRefreshAvailability}
                      disabled={isRefreshingAvailability}
                      loading={isRefreshingAvailability}
                    >
                      {t("agent.config.refreshAvailability")}
                    </Button>
                  </span>
                </div>
              }
            />
          )}
        </div>
        <TabsContent
          value="basic"
          className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1 mt-2"
        >
          {/* 1. 展示信息 */}
          <ConfigSection
            title={t("agent.config.section.displayInfo.title")}
            description={t("agent.config.section.displayInfo.description")}
            icon={<Info className="h-4 w-4 shrink-0 text-blue-500" />}
            open={openSections.display_info}
            onOpenChange={(open) =>
              handleSectionOpenChange("display_info", open)
            }
            containerRef={displayInfoSectionRef}
          >
            <AgentInfo />
          </ConfigSection>

          {/* 2. 角色与模型 */}
          <ConfigSection
            title={t("agent.config.section.roleModel.title")}
            description={t("agent.config.section.roleModel.description")}
            icon={<Cpu className="h-4 w-4 shrink-0 text-blue-500" />}
            open={openSections.role_model}
            onOpenChange={(open) => handleSectionOpenChange("role_model", open)}
            containerRef={roleModelSectionRef}
          >
            <AgentPrmopt />
          </ConfigSection>

          {/* 3. 知识库 */}
          <ConfigSection
            title={t("agent.config.section.knowledgeBase.title")}
            description={t("agent.config.section.knowledgeBase.description")}
            icon={<Database className="h-4 w-4 shrink-0 text-blue-500" />}
            open={openSections.knowledge_base}
            onOpenChange={(open) =>
              handleSectionOpenChange("knowledge_base", open)
            }
            containerRef={knowledgeBaseSectionRef}
            headerActions={<KnowledgeBaseConfigActions />}
          >
            <KnowledgeBaseConfig />
          </ConfigSection>

          {/* 4. 开场白 */}
          <ConfigSection
            title={t("agent.config.section.conversationGuide.title")}
            description={t(
              "agent.config.section.conversationGuide.description"
            )}
            icon={<MessageSquare className="h-4 w-4 shrink-0 text-blue-500" />}
            open={openSections.conversation_guide}
            onOpenChange={(open) =>
              handleSectionOpenChange("conversation_guide", open)
            }
            containerRef={conversationGuideSectionRef}
          >
            <AgentGuide />
          </ConfigSection>
        </TabsContent>

        <TabsContent
          value="tools_skills"
          className={cn("min-h-0 flex-1 space-y-3 overflow-y-auto pr-1 mt-3")}
        >
          <ConfigSection
            title={t("agent.config.section.tools.title")}
            description={t("agent.config.section.tools.description")}
            icon={<Wrench className="h-4 w-4 shrink-0 text-blue-500" />}
            open={openSections.tools}
            onOpenChange={(open) => handleSectionOpenChange("tools", open)}
            containerRef={toolsSectionRef}
          >
            <AgentToolCapability />
          </ConfigSection>
          <ConfigSection
            title={t("agent.config.section.skills.title")}
            description={t("agent.config.section.skills.description")}
            icon={<BlocksIcon className="h-4 w-4 shrink-0 text-blue-500" />}
            open={openSections.skills}
            onOpenChange={(open) => handleSectionOpenChange("skills", open)}
            containerRef={skillsSectionRef}
          >
            <AgentSkillCapability />
          </ConfigSection>
        </TabsContent>

        <TabsContent
          value="advanced"
          className={cn("min-h-0 flex-1 space-y-3 overflow-y-auto pr-1 mt-3")}
        >
          {/* 1. 协同 Agent */}
          <ConfigSection
            title={t("agent.config.section.collaborativeAgents.title")}
            description={t(
              "agent.config.section.collaborativeAgents.description"
            )}
            icon={<Cpu className="h-4 w-4 shrink-0 text-blue-500" />}
            open={openSections.collaborative_agents}
            onOpenChange={(open) =>
              handleSectionOpenChange("collaborative_agents", open)
            }
            containerRef={collaborativeAgentsSectionRef}
            headerActions={<CollaborativeAgentActions />}
          >
            <CollaborativeAgent />
          </ConfigSection>

          {/* 2. 运行策略 */}
          <ConfigSection
            title={t("agent.config.section.runStrategy.title")}
            description={t("agent.config.section.runStrategy.description")}
            icon={<Play className="h-4 w-4 shrink-0 text-blue-500" />}
            open={openSections.run_strategy}
            onOpenChange={(open) =>
              handleSectionOpenChange("run_strategy", open)
            }
            containerRef={runStrategySectionRef}
          >
            <AgentRunPolicy />
          </ConfigSection>

          {/* 3. 发布属性 */}
          <ConfigSection
            title={t("agent.config.section.publishAttributes.title")}
            description={t(
              "agent.config.section.publishAttributes.description"
            )}
            icon={<Globe className="h-4 w-4 shrink-0 text-blue-500" />}
            open={openSections.publish_attributes}
            onOpenChange={(open) =>
              handleSectionOpenChange("publish_attributes", open)
            }
            containerRef={publishAttributesSectionRef}
          >
            <AgentDeployment />
          </ConfigSection>

          {/* 4. 安全护栏 */}
          <ConfigSection
            title={t("agent.config.section.guardrail.title")}
            description={t("agent.config.section.guardrail.description")}
            icon={<ShieldCheck className="h-4 w-4 shrink-0 text-blue-500" />}
            open={openSections.guardrail}
            onOpenChange={(open) => handleSectionOpenChange("guardrail", open)}
            containerRef={guardrailSectionRef}
            headerActions={<GuardrailConfigActions />}
          >
            <GuardrailConfigContent />
          </ConfigSection>
        </TabsContent>
      </Tabs>
      <div
        ref={actionAreaRef}
        className="flex shrink-0 items-center justify-between gap-2 border-t border-gray-200 bg-white pt-3 pb-1"
      >
        <Tooltip title={t("agent.page.panel.nl2agent.manualUnlockAction")}>
          <Button
            aria-label={t("agent.page.panel.nl2agent.manualUnlockAction")}
            icon={<LockOpen size={16} />}
            disabled={!canManualUnlock}
            onClick={onManualUnlock}
            variant="solid"
            type="primary"
          >
            {t("agent.config.button.unlock")}
          </Button>
        </Tooltip>
        <div className="flex items-center gap-2">
          <Button
            icon={<Bug size={16} />}
            disabled={agentId === null}
            onClick={handleDebug}
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
      </div>
      <AgentVersionPubulishModal
        open={isPublishModalOpen}
        onClose={() => setIsPublishModalOpen(false)}
        agentId={agentId}
        onPublished={onPublished}
      />
    </Form>
  );
}
