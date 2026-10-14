"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "next/navigation";
import { App, Alert, Button, ConfigProvider, Form, Modal } from "antd";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { StandardCard } from "@/components/common/StandardCard";
import { useAgentStore } from "@/stores/agentStore";
import { searchAgentInfo } from "@/services/agentConfigService";
import { getUnavailableReasonLabels } from "@/lib/agentLabelMapper";
import { getTenantResourceLimitMessage } from "@/const/errorMessageI18n";
import { useSaveGuard } from "@/hooks/agent/useSaveGuard";
import { useAgentReadOnly } from "@/hooks/agent/useAgentReadOnly";
import { useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import { buildDefaultAgentVersionName } from "@/lib/agentUsageGuide";

import AgentInfo from "./components/agent-info";
import AgentPrmopt from "./components/agent-prompt";
import {
  AgentSkillCapability,
  AgentToolCapability,
} from "./components/agent-capability";
import AgentRunPolicy, {
  AgentProtocolRepairOption,
} from "./components/agent-run-policy";
import AgentGuide from "./components/agent-guide";
import AgentDeployment from "./components/agent-deployment";
import CollaborativeAgent from "./components/collaborative-agent";
import GuardrailConfigContent, {
  GuardrailConfigActions,
} from "./components/advanced/GuardrailConfigContent";
import KnowledgeBaseConfig from "./components/knowledge-base-search";
import AgentVersionPubulishModal from "../versions/AgentVersionPubulishModal";
import { AgentConfigHeader } from "./components/agent-config-header";

import {
  ChevronDown,
  Info,
  ContactRound,
  Box,
  Puzzle,
  GraduationCap,
  BlocksIcon,
  CircleCheck,
  BookOpen,
  ScrollText,
  RefreshCw,
  Settings2,
} from "lucide-react";

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

const DEFAULT_OPEN_SECTIONS: Record<ConfigSectionKey, boolean> = {
  display_info: true,
  role_model: true,
  tools: true,
  skills: true,
  run_strategy: true,
  publish_attributes: true,
  collaborative_agents: true,
  knowledge_base: true,
  conversation_guide: true,
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
  card?: boolean;
  basic?: boolean;
  testId?: string;
  referenceMinHeight?: number;
  contentGap?: 4 | 8;
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
  card = true,
  basic = false,
  testId,
  referenceMinHeight,
  contentGap = 8,
}: ConfigSectionProps) {
  const section = (
    <div
      ref={containerRef}
      data-testid={card ? undefined : testId}
      className="min-w-0"
    >
      <Collapsible
        open={open}
        onOpenChange={onOpenChange}
        className="w-full min-w-0"
      >
        <div
          className={`flex items-start justify-between gap-4 ${description ? "min-h-[50px]" : "min-h-6"}`}
        >
          <CollapsibleTrigger className="group flex min-w-0 flex-1 cursor-pointer select-none flex-col items-start gap-1 text-left">
            <div className="flex h-6 min-w-0 items-center gap-2">
              <div className="flex min-w-0 items-center gap-2 text-base font-medium leading-6 tracking-[0px] text-[#191919] [font-family:'HarmonyOS_Sans_SC','Huawei_Sans',sans-serif]">
                {icon}
                <span className="truncate">{title}</span>
                <ChevronDown className="h-4 w-4 shrink-0 text-[#191919] transition-transform group-data-[state=open]:rotate-180" />
              </div>
            </div>
            {description && (
              <p className="min-h-[22px] max-w-full text-xs font-normal leading-[22px] tracking-[0px] text-[#808080]">
                {description}
              </p>
            )}
          </CollapsibleTrigger>
          {headerActions && (
            <div className="flex shrink-0 items-center gap-2">
              {headerActions}
            </div>
          )}
        </div>
        <CollapsibleContent
          forceMount
          className={`${contentGap === 4 ? "pt-1" : "pt-2"} data-[state=closed]:hidden`}
        >
          {children}
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
  return card ? (
    <StandardCard
      data-testid={testId}
      className={
        basic
          ? "shrink-0 ![box-shadow:none] !rounded-lg !px-6 !py-[18px]"
          : "shrink-0 ![box-shadow:none] !rounded-lg !px-6 !py-4"
      }
      styles={{ body: { padding: 0 } }}
      style={
        open && referenceMinHeight
          ? { minHeight: referenceMinHeight }
          : undefined
      }
    >
      {section}
    </StandardCard>
  ) : (
    section
  );
}

interface AgentConfigProps {
  creationGuideActive?: boolean;
  published?: boolean;
  canManualUnlock: boolean;
  onManualUnlock: () => void;
  onToggleDebug: () => void;
  actionAreaRef?: React.Ref<HTMLDivElement>;
  onPublished?: () => void;
  debugVisible?: boolean;
  onConfigure?: () => void;
  onOptimizePrompt?: () => void;
  debugPanel?: ReactNode;
  debugExpanded?: boolean;
}

export default function AgentConfig({
  creationGuideActive = false,
  published = false,
  canManualUnlock,
  onManualUnlock,
  onToggleDebug,
  actionAreaRef,
  onPublished,
  debugVisible = false,
  onConfigure = () => undefined,
  onOptimizePrompt,
  debugPanel,
  debugExpanded = false,
}: AgentConfigProps) {
  const { t } = useTranslation("common");
  const searchParams = useSearchParams();
  const [form] = Form.useForm();
  const [isPublishModalOpen, setIsPublishModalOpen] = useState(false);
  const publishIntentHandledForAgentRef = useRef<number | null>(null);
  const [isRefreshingAvailability, setIsRefreshingAvailability] =
    useState(false);
  const agentId = useAgentStore((state) => state.agentId);
  const [sectionState, setSectionState] = useState(() => ({
    agentId,
    openSections: { ...DEFAULT_OPEN_SECTIONS },
  }));
  if (sectionState.agentId !== agentId) {
    setSectionState({
      agentId,
      openSections: { ...DEFAULT_OPEN_SECTIONS },
    });
  }
  const openSections = sectionState.openSections;
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
  const { save } = useSaveGuard();
  const { message } = App.useApp();
  const saveError = useAgentStore((state) => state.saveError);
  const clearSaveError = useAgentStore((state) => state.clearSaveError);
  const replaceServerSnapshot = useAgentStore(
    (state) => state.replaceServerSnapshot
  );

  const handleRefreshAvailability = useCallback(async () => {
    if (!agentId || isRefreshingAvailability) return;
    setIsRefreshingAvailability(true);
    try {
      const result = await searchAgentInfo(agentId);
      if (result.success && result.data) {
        replaceServerSnapshot(agentId, result.data);
      } else {
        message.error(
          result.message || t("agent.config.refreshAvailabilityFailed")
        );
      }
    } catch {
      message.error(t("agent.config.refreshAvailabilityFailed"));
    } finally {
      setIsRefreshingAvailability(false);
    }
  }, [agentId, isRefreshingAvailability, message, replaceServerSnapshot, t]);

  useEffect(() => {
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
    setSectionState((current) => {
      const sections =
        current.agentId === agentId
          ? current.openSections
          : DEFAULT_OPEN_SECTIONS;
      return sections[targetSection]
        ? current
        : {
            agentId,
            openSections: { ...sections, [targetSection]: true },
          };
    });

    lastScrolledRequestRef.current = requestKey;
    const frameId = window.requestAnimationFrame(() => {
      const sectionRefs: Record<
        ConfigSectionKey,
        React.RefObject<HTMLDivElement | null>
      > = {
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

  const handleSectionOpenChange = useCallback(
    (section: ConfigSectionKey, open: boolean) => {
      setSectionState((current) => {
        const sections =
          current.agentId === agentId
            ? current.openSections
            : DEFAULT_OPEN_SECTIONS;
        return sections[section] === open
          ? current
          : {
              agentId,
              openSections: { ...sections, [section]: open },
            };
      });
    },
    [agentId]
  );

  const handleDebug = async () => {
    try {
      await form.validateFields();
      if (!(await save())) return;
      onToggleDebug();
    } catch {
      handleSectionOpenChange("display_info", true);
      handleSectionOpenChange("role_model", true);
      // Field validation errors are rendered by Ant Design.
    }
  };

  const handlePublish = async () => {
    try {
      await form.validateFields();
      if (!(await save())) return;
      setIsPublishModalOpen(true);
    } catch {
      handleSectionOpenChange("display_info", true);
      handleSectionOpenChange("role_model", true);
      // Field validation errors are rendered by Ant Design.
    }
  };

  useEffect(() => {
    if (
      searchParams.get("publish") !== "1" ||
      agentId === null ||
      !editedAgent ||
      isReadOnly ||
      publishIntentHandledForAgentRef.current === agentId
    ) {
      return;
    }

    publishIntentHandledForAgentRef.current = agentId;
    void form
      .validateFields()
      .then(async () => {
        if (await save()) setIsPublishModalOpen(true);
      })
      .catch(() => {
        handleSectionOpenChange("display_info", true);
        handleSectionOpenChange("role_model", true);
        // Field validation errors are rendered by Ant Design.
      });
  }, [
    agentId,
    editedAgent,
    form,
    handleSectionOpenChange,
    isReadOnly,
    save,
    searchParams,
  ]);

  useEffect(() => {
    if (!saveError) {
      return;
    }

    message.error(
      getTenantResourceLimitMessage(saveError, t) ||
        (saveError instanceof Error ? saveError.message : saveError)
    );
    clearSaveError();
  }, [clearSaveError, message, saveError, t]);

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
    <ConfigProvider
      button={{ autoInsertSpace: false }}
      theme={{
        token: {
          fontFamily:
            '"Huawei Sans", "HarmonyOS Sans SC", system-ui, sans-serif',
          fontSize: 14,
          lineHeight: 22 / 14,
          colorPrimary: "#2673E5",
          colorText: "#191919",
          colorTextPlaceholder: "#AEAEAE",
          colorBorder: "#C9C9C9",
          controlHeight: 32,
          borderRadius: 4,
        },
        components: {
          Form: {
            verticalLabelPadding: "0 0 8px",
            labelColor: "#191919",
            labelFontSize: 14,
          },
        },
      }}
    >
      <Form
        component="div"
        form={form}
        layout="vertical"
        disabled={isReadOnly}
        className="flex h-full min-h-0 flex-col bg-[#f3f3f3] [&_.ant-form-item-label>label]:!h-[22px]"
      >
        <AgentConfigHeader
          published={published}
          agent={editedAgent}
          agentId={agentId}
          readOnly={isReadOnly}
          debugVisible={debugVisible}
          canManualUnlock={canManualUnlock}
          onEditIdentity={() => {
            handleSectionOpenChange("display_info", true);
          }}
          onConfigure={onConfigure}
          onDebug={handleDebug}
          onPublish={handlePublish}
          onManualUnlock={onManualUnlock}
          actionAreaRef={actionAreaRef}
        />
        <div
          className={
            debugVisible
              ? "flex min-h-0 min-w-0 flex-1 gap-[10px] pl-4 pr-[18px] pb-3"
              : "flex min-h-0 min-w-0 flex-1"
          }
        >
          <div
            data-testid="agent-config-scroll-region"
            className={
              debugExpanded && debugVisible
                ? "hidden"
                : debugVisible
                  ? "flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-y-auto"
                  : "flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-y-auto pl-4 pr-[18px] pb-4"
            }
          >
            {unavailableReasonLabels.length > 0 && (
              <Alert
                className="shrink-0"
                type="warning"
                showIcon
                title={
                  <span className="flex items-center justify-between gap-2">
                    <span>{`${t("agent.unavailable")}${unavailableReasonLabels.join("、")}`}</span>
                    <Button
                      type="link"
                      size="small"
                      icon={
                        <RefreshCw
                          size={12}
                          className={
                            isRefreshingAvailability ? "animate-spin" : ""
                          }
                        />
                      }
                      onClick={handleRefreshAvailability}
                      disabled={isRefreshingAvailability}
                      loading={isRefreshingAvailability}
                    >
                      {t("agent.config.refreshAvailability")}
                    </Button>
                  </span>
                }
              />
            )}
            <div
              data-agent-guide="core"
              className="flex shrink-0 flex-col gap-3"
            >
              <ConfigSection
                testId="agent-config-card-info"
                basic
                referenceMinHeight={224}
                title={t("agent.highFidelity.basicTitle")}
                description={t("agent.highFidelity.basicDescription")}
                icon={<ContactRound className="size-6 shrink-0" />}
                open={openSections.display_info}
                onOpenChange={(open) =>
                  handleSectionOpenChange("display_info", open)
                }
                containerRef={displayInfoSectionRef}
              >
                <AgentInfo highFidelity guideCompact={creationGuideActive} />
              </ConfigSection>
              <ConfigSection
                testId="agent-config-card-model"
                referenceMinHeight={creationGuideActive ? 272 : 268}
                title={t("agent.highFidelity.modelTitle")}
                description={t("agent.highFidelity.modelDescription")}
                icon={<Box className="size-6 shrink-0" />}
                open={openSections.role_model}
                onOpenChange={(open) =>
                  handleSectionOpenChange("role_model", open)
                }
                containerRef={roleModelSectionRef}
              >
                <AgentPrmopt highFidelity onOptimizePrompt={onOptimizePrompt} />
              </ConfigSection>
            </div>
            <StandardCard
              data-testid="agent-config-card-resources"
              className="relative shrink-0 ![box-shadow:none] !rounded-lg !px-6 !py-4"
              styles={{
                body: {
                  padding: 0,
                  display: "flex",
                  flexDirection: "column",
                  gap: 16,
                },
              }}
            >
              <span
                aria-hidden
                data-agent-guide="resources"
                className="pointer-events-none absolute inset-x-0 -top-[4.5px] bottom-[4.5px]"
              />
              <KnowledgeBaseConfig
                highFidelity
                renderSection={(content, actions) => (
                  <ConfigSection
                    card={false}
                    title={t("agent.highFidelity.knowledgeTitle")}
                    description={t("agent.highFidelity.knowledgeDescription")}
                    icon={<BookOpen className="size-6 shrink-0" />}
                    open={openSections.knowledge_base && !creationGuideActive}
                    onOpenChange={(open) =>
                      handleSectionOpenChange("knowledge_base", open)
                    }
                    containerRef={knowledgeBaseSectionRef}
                    headerActions={actions}
                  >
                    {content}
                  </ConfigSection>
                )}
              />
              <ConfigSection
                card={false}
                title={t("agent.highFidelity.guideTitle")}
                description={t("agent.highFidelity.guideDescription")}
                icon={<ScrollText className="size-6 shrink-0" />}
                open={openSections.conversation_guide && !creationGuideActive}
                onOpenChange={(open) =>
                  handleSectionOpenChange("conversation_guide", open)
                }
                containerRef={conversationGuideSectionRef}
              >
                <AgentGuide highFidelity />
              </ConfigSection>
              <AgentSkillCapability
                highFidelity
                renderSection={(content, actions) => (
                  <ConfigSection
                    card={false}
                    title={t("agent.highFidelity.skillTitle")}
                    description={t("agent.highFidelity.skillDescription")}
                    icon={<GraduationCap className="size-6 shrink-0" />}
                    open={openSections.skills && !creationGuideActive}
                    onOpenChange={(open) =>
                      handleSectionOpenChange("skills", open)
                    }
                    containerRef={skillsSectionRef}
                    headerActions={actions}
                  >
                    {content}
                  </ConfigSection>
                )}
              />
              <AgentToolCapability
                highFidelity
                renderSection={(content, actions) => (
                  <ConfigSection
                    card={false}
                    title={t("agent.highFidelity.toolTitle")}
                    description={t("agent.highFidelity.toolDescription")}
                    icon={<Puzzle className="size-6 shrink-0" />}
                    open={openSections.tools && !creationGuideActive}
                    onOpenChange={(open) =>
                      handleSectionOpenChange("tools", open)
                    }
                    containerRef={toolsSectionRef}
                    headerActions={actions}
                  >
                    {content}
                  </ConfigSection>
                )}
              />
              <CollaborativeAgent
                highFidelity
                renderSection={(content, actions) => (
                  <ConfigSection
                    card={false}
                    title={t("agent.highFidelity.childTitle")}
                    description={t("agent.highFidelity.childDescription")}
                    icon={<BlocksIcon className="size-6 shrink-0" />}
                    open={
                      openSections.collaborative_agents && !creationGuideActive
                    }
                    onOpenChange={(open) =>
                      handleSectionOpenChange("collaborative_agents", open)
                    }
                    containerRef={collaborativeAgentsSectionRef}
                    headerActions={actions}
                  >
                    {content}
                  </ConfigSection>
                )}
              />
            </StandardCard>
            <StandardCard
              data-testid="agent-config-card-advanced"
              className="shrink-0 ![box-shadow:none] !rounded-lg !px-6 !py-4"
              styles={{
                body: {
                  padding: 0,
                  display: "flex",
                  flexDirection: "column",
                  gap: 16,
                },
              }}
            >
              <ConfigSection
                card={false}
                title={t("agent.highFidelity.permissionTitle")}
                description={t("agent.highFidelity.permissionDescription")}
                icon={<CircleCheck className="size-6 shrink-0" />}
                open={openSections.publish_attributes}
                onOpenChange={(open) =>
                  handleSectionOpenChange("publish_attributes", open)
                }
                containerRef={publishAttributesSectionRef}
              >
                <AgentDeployment highFidelity />
              </ConfigSection>
              <ConfigSection
                card={false}
                title={t("agent.highFidelity.advancedTitle")}
                description=""
                icon={<Settings2 className="size-6 shrink-0" />}
                open={openSections.run_strategy}
                onOpenChange={(open) =>
                  handleSectionOpenChange("run_strategy", open)
                }
                containerRef={runStrategySectionRef}
                headerActions={
                  <Button
                    type="text"
                    size="small"
                    aria-label={t("agent.highFidelity.moreSettings")}
                    icon={<Settings2 size={16} />}
                    onClick={() => handleSectionOpenChange("guardrail", true)}
                    className="!size-6 !p-0"
                  />
                }
              >
                <AgentRunPolicy highFidelity />
              </ConfigSection>
            </StandardCard>
            <Modal
              title={t("agent.highFidelity.moreSettings")}
              open={openSections.guardrail}
              onCancel={() => handleSectionOpenChange("guardrail", false)}
              footer={null}
              forceRender
              width={800}
            >
              <div ref={guardrailSectionRef} className="flex flex-col gap-4">
                <AgentProtocolRepairOption />
                <div className="flex items-center justify-between">
                  <span className="text-base font-medium">
                    {t("agent.config.section.guardrail.title")}
                  </span>
                  <GuardrailConfigActions />
                </div>
                <GuardrailConfigContent />
              </div>
            </Modal>
          </div>
          <ConfigProvider componentDisabled={false}>
            {debugPanel}
          </ConfigProvider>
        </div>
        <AgentVersionPubulishModal
          open={isPublishModalOpen}
          onClose={() => setIsPublishModalOpen(false)}
          agentId={agentId}
          defaultVersionName={buildDefaultAgentVersionName(
            editedAgent.display_name || editedAgent.name
          )}
          onPublished={onPublished}
        />
      </Form>
    </ConfigProvider>
  );
}
