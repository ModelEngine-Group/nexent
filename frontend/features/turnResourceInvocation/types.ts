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

export interface TurnResourceReference {
  resource_type: Exclude<TurnResourceType, "automation">;
  resource_id: string;
  name: string;
}

export interface TurnResourceRequest {
  mode: "required";
  resources: TurnResourceReference[];
}

export interface TurnResourceSelection {
  key: string;
  resourceType: TurnResourceType;
  mode: TurnResourceInvocationMode;
  label: string;
  description: string;
  command?: TurnResourceCommandDefinition;
  reference?: TurnResourceReference;
}
