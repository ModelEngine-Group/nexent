const FINAL_ENVELOPE = /^<final_answer>([\s\S]*)<\/final_answer>$/;

export function unwrapFinalAnswer(value: string): string {
  if (typeof value !== "string") return value;

  const trimmed = value.trim();
  const match = FINAL_ENVELOPE.exec(trimmed);
  if (!match) return value;

  const body = match[1];
  if (
    !body.trim() ||
    body.includes("<final_answer>") ||
    body.includes("</final_answer>")
  ) {
    return value;
  }

  return body;
}
