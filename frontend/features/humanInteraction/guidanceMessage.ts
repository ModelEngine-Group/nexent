export interface GuidanceMessage {
  request_id: string;
  text: string;
  created_at: string;
}

export interface GuidanceMessagePart {
  type: "data";
  name: "user-steering";
  data: GuidanceMessage;
}

export function parseGuidanceMessage(value: unknown): GuidanceMessage | null {
  try {
    const item = typeof value === "string" ? JSON.parse(value) : value;
    if (
      !item ||
      typeof item.request_id !== "string" ||
      !item.request_id ||
      typeof item.text !== "string" ||
      !item.text.trim() ||
      typeof item.created_at !== "string"
    )
      return null;
    return {
      request_id: item.request_id,
      text: item.text,
      created_at: item.created_at,
    };
  } catch {
    return null;
  }
}

export function appendGuidanceMessage(
  parts: unknown[],
  value: unknown
): boolean {
  const data = parseGuidanceMessage(value);
  if (
    !data ||
    parts.some((part) => {
      const item = part as Partial<GuidanceMessagePart> | null;
      return (
        item?.type === "data" &&
        item.name === "user-steering" &&
        item.data?.request_id === data.request_id
      );
    })
  )
    return false;
  parts.push({
    type: "data",
    name: "user-steering",
    data,
  } satisfies GuidanceMessagePart);
  return true;
}
