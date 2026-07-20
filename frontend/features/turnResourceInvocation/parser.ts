import { TURN_RESOURCE_COMMANDS } from "./registry";
import type {
  TurnResourceCommandDefinition,
  TurnResourceInvocation,
  TurnResourceType,
} from "./types";

export function parseTurnResourceInvocation(
  message: string
): TurnResourceInvocation | null {
  const sourceMessage = message.trim();
  if (!sourceMessage.startsWith("/")) return null;

  const separatorIndex = sourceMessage.search(/\s/);
  const command =
    separatorIndex === -1
      ? sourceMessage
      : sourceMessage.slice(0, separatorIndex);
  const definition = TURN_RESOURCE_COMMANDS.find(
    (candidate) => candidate.command.toLowerCase() === command.toLowerCase()
  );
  if (!definition) return null;

  return {
    definition,
    argument:
      separatorIndex === -1 ? "" : sourceMessage.slice(separatorIndex).trim(),
    sourceMessage,
  };
}

export function getTurnResourceCommandSuggestions(
  input: string
): readonly TurnResourceCommandDefinition[] {
  const normalized = input.trimStart();
  if (!normalized.startsWith("/") || /\s/.test(normalized)) return [];

  const query = normalized.toLowerCase();
  return TURN_RESOURCE_COMMANDS.filter((definition) =>
    definition.command.toLowerCase().startsWith(query)
  );
}

export function isTurnResourceType(
  invocation: TurnResourceInvocation | null,
  resourceType: TurnResourceType
): invocation is TurnResourceInvocation {
  return invocation?.definition.resourceType === resourceType;
}
