// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { Collapse, Flex } from "antd";
import { useTranslation } from "react-i18next";
import type { ExperimentReport, Workspace } from "@/services/evolutionService";
import type { EvolutionDirection } from "./EvolutionDirections";
import DiscoveryFeedback from "./DiscoveryFeedback";
import ExampleCandidates from "./ExampleCandidates";
import NewSkillBriefForm from "./NewSkillBriefForm";
import { ScriptFeedbackForm } from "./SkillScriptRepair";
import ToolMappingCandidate from "./ToolMappingCandidate";
import { ToolRepairForm } from "./ToolRepair";
import ToolSetCandidates from "./ToolSetCandidates";

export default function EvolutionGenerationMethods({ direction, baseline, report, workspace, scope, onResource, onScript, onCandidate }: {
  direction?: EvolutionDirection;
  baseline: boolean;
  report: ExperimentReport;
  workspace: Workspace;
  scope: { agent: number; version: number; viewer: string };
  onResource: (id: number) => void;
  onScript: (id: number) => void;
  onCandidate: (kind: string, id: number) => void;
}) {
  const { t } = useTranslation("common");
  const showSkill = !direction || direction === "skill";
  const methods = <Flex vertical gap={12}>
    {(!direction || direction === "prompt") && <ExampleCandidates report={report} cases={workspace.cases}
      onGenerated={(id) => onCandidate("prompt", id)} />}
    {showSkill && Object.values(report.pairs).some(pair => pair.base.result?.selection) &&
      <DiscoveryFeedback report={report} workspace={workspace} onFeedback={onResource} />}
    {showSkill && baseline && <>
      <NewSkillBriefForm report={report} workspace={workspace} onFeedback={onResource} />
      <ScriptFeedbackForm report={report} workspace={workspace} {...scope} onFeedback={onScript} />
    </>}
    {(!direction || direction === "tool") && baseline && <>
      <ToolMappingCandidate report={report} cases={workspace.cases} onSelect={id => onCandidate("tool_mapping", id)} />
      <ToolSetCandidates report={report} cases={workspace.cases} onSelect={id => onCandidate("tool_set", id)} />
      <ToolRepairForm report={report} workspace={workspace} {...scope} />
    </>}
  </Flex>;

  return direction ? methods : <Collapse ghost items={[{ key: "resources", label: t("evolution.workflow.moreMethods"), children: methods }]} />;
}
