import { CREATE_AUTOMATION_TASK_COMMAND } from "@/features/agentAutomation/turnResourceCommand";

import type { TurnResourceCommandDefinition } from "./types";

export const TURN_RESOURCE_COMMANDS: readonly TurnResourceCommandDefinition[] =
  [CREATE_AUTOMATION_TASK_COMMAND];
