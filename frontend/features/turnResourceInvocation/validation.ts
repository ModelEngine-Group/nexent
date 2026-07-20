import type { TurnResourceInvocation } from "./types";

export type TurnResourceInvocationValidationError =
  | "argumentRequired"
  | "attachmentsNotSupported";

export function validateTurnResourceInvocation(
  invocation: TurnResourceInvocation,
  attachmentCount: number
): TurnResourceInvocationValidationError | null {
  if (
    invocation.definition.argumentRequired &&
    invocation.argument.length === 0
  ) {
    return "argumentRequired";
  }
  if (
    invocation.definition.attachmentPolicy === "forbid" &&
    attachmentCount > 0
  ) {
    return "attachmentsNotSupported";
  }
  return null;
}
