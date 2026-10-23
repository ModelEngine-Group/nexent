import type { WorkbenchResourceControls } from "../types";
import type { ConversationKnowledgeScope } from "@/types/knowledgeScope";

export function SelectedResourceChips({
  resources,
  scope,
  knowledgeNames,
  disabled,
  onEditSkill,
  onRemoveSkill,
  onEditKnowledge,
  onKnowledgeChange,
}: {
  resources: WorkbenchResourceControls;
  scope?: ConversationKnowledgeScope | null;
  knowledgeNames?: Partial<Record<"local" | "aidp", Record<string, string>>>;
  disabled?: boolean;
  onEditSkill?: () => void;
  onRemoveSkill?: (id: number) => void;
  onEditKnowledge: () => void;
  onKnowledgeChange?: (scope: ConversationKnowledgeScope) => void;
}) {
  const chips = [
    ...(resources.agents
      ? resources.agents.map((agent) => ({
          key: `agent:${agent.id}`,
          label: `Agent · ${agent.name}`,
          edit: resources.onSelectAgent,
          remove: agent.remove,
        }))
      : resources.agentName
        ? [
            {
              key: "agent",
              label: `Agent · ${resources.agentName}`,
              edit: resources.onSelectAgent,
              remove: resources.onRemoveAgent,
            },
          ]
        : []),
    ...resources.skills.map((skill) => ({
      key: `skill:${skill.id}`,
      label: `Skill · ${skill.name}`,
      edit: onEditSkill,
      remove: () => onRemoveSkill?.(skill.id),
    })),
    ...(["local", "aidp"] as const).flatMap((source) => {
      if (!scope || scope[source].mode === "disabled") return [];
      const ids =
        source === "local" ? scope.local.knowledge_ids : scope.aidp.kds_ids;
      const inherited = scope[source].mode === "inherit";
      return (inherited ? ["default"] : ids).map((id) => ({
        key: `kb:${source}:${id}`,
        label: `知识库 · ${inherited ? "默认" : knowledgeNames?.[source]?.[id] || `#${id}`}`,
        edit: onEditKnowledge,
        remove: () => {
          const nextIds = inherited ? [] : ids.filter((value) => value !== id);
          const mode = nextIds.length
            ? ("override" as const)
            : ("disabled" as const);
          onKnowledgeChange?.({
            ...scope,
            [source]:
              source === "local"
                ? { mode, knowledge_ids: nextIds }
                : { mode, kds_ids: nextIds },
          });
        },
      }));
    }),
  ];
  if (chips.length === 0) return null;
  return (
    <div
      className="mx-4 mb-2 flex min-w-0 flex-wrap gap-1.5 pt-2"
      aria-label="当前挂载资源"
    >
      {chips.map((chip) => (
        <span
          key={chip.key}
          className="inline-flex max-w-60 items-center rounded-full bg-muted text-xs"
        >
          <button
            type="button"
            disabled={disabled}
            className="truncate px-2.5 py-1 focus-visible:ring-2"
            onClick={chip.edit}
            title={chip.label}
          >
            {chip.label}
          </button>
          <button
            type="button"
            disabled={disabled}
            className="px-2 py-1 hover:text-destructive focus-visible:ring-2"
            aria-label={`移除 ${chip.label}`}
            onClick={chip.remove}
          >
            ×
          </button>
        </span>
      ))}
    </div>
  );
}
