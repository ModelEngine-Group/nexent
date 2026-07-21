const EMOJI_PICTOGRAPHIC = /\p{Extended_Pictographic}/gu;
const EMOJI_MODIFIERS = /[\uFE0E\uFE0F\u{1F3FB}-\u{1F3FF}]/gu;

/**
 * Returns true when value is a single simple emoji (no ZWJ compounds, flags, or text).
 */
export function isSingleSimpleEmoji(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed) {
    return false;
  }

  if (trimmed.includes("\u200D")) {
    return false;
  }

  const pictographics = trimmed.match(EMOJI_PICTOGRAPHIC) ?? [];
  if (pictographics.length !== 1) {
    return false;
  }

  const remainder = trimmed
    .replace(EMOJI_PICTOGRAPHIC, "")
    .replace(EMOJI_MODIFIERS, "");

  return remainder.length === 0;
}
