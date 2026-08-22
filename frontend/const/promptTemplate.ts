export const PROMPT_TEMPLATE_FIELD_CONFIG = [
  {
    key: "duty_system_prompt",
    labelKey: "systemPrompt.card.duty.title",
    section: "basic",
  },
  {
    key: "constraint_system_prompt",
    labelKey: "systemPrompt.card.constraint.title",
    section: "basic",
  },
  {
    key: "few_shots_system_prompt",
    labelKey: "systemPrompt.card.fewShots.title",
    section: "basic",
  },
  {
    key: "user_prompt",
    labelKey: "businessLogic.config.template.field.userPrompt",
    section: "basic",
  },
  {
    key: "agent_variable_name_system_prompt",
    labelKey: "businessLogic.config.template.field.agentVariableName",
    section: "advanced",
  },
  {
    key: "agent_display_name_system_prompt",
    labelKey: "businessLogic.config.template.field.agentDisplayName",
    section: "advanced",
  },
  {
    key: "agent_description_system_prompt",
    labelKey: "businessLogic.config.template.field.agentDescription",
    section: "advanced",
  },
  {
    key: "agent_name_regenerate_system_prompt",
    labelKey: "businessLogic.config.template.field.agentNameRegenerateSystem",
    section: "advanced",
  },
  {
    key: "agent_name_regenerate_user_prompt",
    labelKey: "businessLogic.config.template.field.agentNameRegenerateUser",
    section: "advanced",
  },
  {
    key: "agent_display_name_regenerate_system_prompt",
    labelKey: "businessLogic.config.template.field.agentDisplayNameRegenerateSystem",
    section: "advanced",
  },
  {
    key: "agent_display_name_regenerate_user_prompt",
    labelKey: "businessLogic.config.template.field.agentDisplayNameRegenerateUser",
    section: "advanced",
  },
] as const;

export type PromptTemplateFieldConfig = (typeof PROMPT_TEMPLATE_FIELD_CONFIG)[number];
export type PromptTemplateFieldKey = PromptTemplateFieldConfig["key"];

export const PROMPT_TEMPLATE_FIELD_KEYS = PROMPT_TEMPLATE_FIELD_CONFIG.map(
  (field) => field.key
) as PromptTemplateFieldKey[];

export const BASIC_PROMPT_TEMPLATE_FIELDS = PROMPT_TEMPLATE_FIELD_CONFIG.filter(
  (field) => field.section === "basic"
);

export const ADVANCED_PROMPT_TEMPLATE_FIELDS = PROMPT_TEMPLATE_FIELD_CONFIG.filter(
  (field) => field.section === "advanced"
);

export function createEmptyPromptTemplateContent(): Record<PromptTemplateFieldKey, string> {
  return PROMPT_TEMPLATE_FIELD_KEYS.reduce(
    (content, key) => {
      content[key] = "";
      return content;
    },
    {} as Record<PromptTemplateFieldKey, string>
  );
}
