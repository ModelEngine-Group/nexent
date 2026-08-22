const AGENT_NAME_PATTERN = /^[a-zA-Z_][a-zA-Z0-9_]*$/;

export const AGENT_NAME_MAX_LENGTH = 60;
export const AGENT_DESCRIPTION_MAX_LENGTH = 500;

export const isValidAgentName = (name: string): boolean =>
  name.length <= AGENT_NAME_MAX_LENGTH && AGENT_NAME_PATTERN.test(name);

export const isValidAgentDisplayName = (name: string): boolean =>
  name.length <= AGENT_NAME_MAX_LENGTH;

export const isValidAgentDescription = (description: string): boolean =>
  description.length <= AGENT_DESCRIPTION_MAX_LENGTH;
