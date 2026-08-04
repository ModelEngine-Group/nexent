import type { Skill, SkillParam } from "@/types/agentConfig";

const isMissingRequiredValue = (value: unknown): boolean =>
  value === undefined || value === null || value === "";

const getEffectiveParamValue = (
  param: SkillParam,
  configValues: Record<string, unknown>
): unknown =>
  Object.prototype.hasOwnProperty.call(configValues, param.name)
    ? configValues[param.name]
    : param.value;

export const withEffectiveSkillConfig = (
  skill: Skill,
  savedConfigValues?: Record<string, unknown> | null
): Skill => {
  const schemaDefaults = Object.fromEntries(
    (skill.config_schemas || []).map((param) => [param.name, param.value])
  );
  const skillConfigValues =
    skill.config_values && typeof skill.config_values === "object"
      ? skill.config_values
      : {};

  return {
    ...skill,
    config_values: {
      ...schemaDefaults,
      ...skillConfigValues,
      ...(savedConfigValues || {}),
    },
  };
};

export const hasMissingRequiredSkillConfig = (skill: Skill): boolean => {
  const configValues =
    skill.config_values && typeof skill.config_values === "object"
      ? skill.config_values
      : {};

  return (skill.config_schemas || []).some(
    (param) =>
      param.required &&
      isMissingRequiredValue(getEffectiveParamValue(param, configValues))
  );
};

export const requiresSkillConfigOnSelection = (skill: Skill): boolean =>
  skill.name.toLowerCase() === "search-knowledge-base";
