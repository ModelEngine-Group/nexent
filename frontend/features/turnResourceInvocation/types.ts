export type TurnResourceType =
  | "automation"
  | "skill"
  | "knowledge"
  | "mcp"
  | "subagent";

export type TurnResourceInvocationMode = "intercept" | "augment";

export interface TurnResourceCommandDefinition {
  id: string;
  command: `/${string}`;
  resourceType: TurnResourceType;
  mode: TurnResourceInvocationMode;
  argumentRequired: boolean;
  attachmentPolicy: "allow" | "forbid";
  titleKey: string;
  descriptionKey: string;
}

export interface TurnResourceInvocation {
  definition: TurnResourceCommandDefinition;
  argument: string;
  sourceMessage: string;
}
