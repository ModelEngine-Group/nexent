import type { TurnResourceCommandDefinition } from "@/features/turnResourceInvocation/types";

export const CREATE_AUTOMATION_TASK_COMMAND = {
  id: "create-automation-task",
  command: "/create-automation-task",
  resourceType: "automation",
  mode: "intercept",
  argumentRequired: true,
  attachmentPolicy: "forbid",
  titleKey: "turnResourceInvocation.automation.title",
  descriptionKey: "turnResourceInvocation.automation.description",
} as const satisfies TurnResourceCommandDefinition;
