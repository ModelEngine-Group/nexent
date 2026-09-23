const FINAL_ENVELOPE = /^<FINAL_ANSWER>([\s\S]*)<\/FINAL_ANSWER>$/;

export function unwrapFinalAnswer(value: string): string {
  if (typeof value !== "string") return value;

  const trimmed = value.trim();
  const match = FINAL_ENVELOPE.exec(trimmed);
  if (!match) return value;

  const body = match[1];
  if (
    !body.trim() ||
    body.includes("<FINAL_ANSWER>") ||
    body.includes("</FINAL_ANSWER>")
  ) {
    return value;
  }

  return body;
}
