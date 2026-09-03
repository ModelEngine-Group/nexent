import type { TFunction } from "i18next";

import { getAgentRepositoryTagLabel } from "@/lib/agentRepositoryLabels";
import type { TagDefinition, TagResourcePredicate } from "@/types/tagManagement";

const SYSTEM_DEFINITION_I18N_KEYS: Record<string, string> = {
  agent_category: "tagManagement.systemDefinition.agentCategory",
  keywords: "tagManagement.systemDefinition.keywords",
};

export function getTagDefinitionDisplayName(
  definitionKey: string,
  definitionName: string,
  t: TFunction
): string {
  const i18nKey = SYSTEM_DEFINITION_I18N_KEYS[definitionKey];
  if (!i18nKey) return definitionName;
  const translated = t(i18nKey);
  return translated === i18nKey ? definitionName : translated;
}

export function getTagValueDisplayName(
  definitionKey: string,
  displayValue: string,
  t: TFunction
): string {
  if (definitionKey === "agent_category") {
    return getAgentRepositoryTagLabel(displayValue, t);
  }
  return displayValue;
}

export function getTagSearchPredicates(
  definitions: TagDefinition[] | null | undefined,
  search: string,
  t: TFunction
): TagResourcePredicate[] {
  const keyword = search.trim().toLocaleLowerCase();
  if (!keyword) return [];

  return (definitions ?? []).flatMap((definition) => {
    const definitionMatches = [
      getTagDefinitionDisplayName(
        definition.definition_key,
        definition.definition_name,
        t
      ),
      definition.definition_key,
    ].some((value) => value.toLocaleLowerCase().includes(keyword));
    const valueIds = (definition.values ?? [])
      .filter(
        (value) =>
          value.status === "active" &&
          (definitionMatches ||
            [
              getTagValueDisplayName(
                definition.definition_key,
                value.display_value,
                t
              ),
              value.normalized_value,
            ].some((candidate) => candidate.toLocaleLowerCase().includes(keyword)))
      )
      .map((value) => value.value_id);
    return valueIds.length > 0
      ? [{ definition_id: definition.definition_id, value_ids: valueIds }]
      : [];
  });
}
