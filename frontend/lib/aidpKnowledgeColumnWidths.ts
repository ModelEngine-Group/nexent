export const AIDP_MIN_COLUMN_WIDTH = 64;

/** Distribute available space proportionally, freezing columns at the minimum. */
export function fitAidpColumnWidths<K extends string>(
  keys: readonly K[],
  weights: Record<K, number>,
  containerWidth: number
): Record<K, number> {
  const widths = {} as Record<K, number>;
  let remaining = [...keys];
  let space = Math.max(containerWidth, keys.length * AIDP_MIN_COLUMN_WIDTH);
  while (remaining.length) {
    const totalWeight = remaining.reduce((sum, key) => sum + weights[key], 0);
    const constrained = remaining.filter(
      (key) => (space * weights[key]) / totalWeight < AIDP_MIN_COLUMN_WIDTH
    );
    if (!constrained.length) {
      remaining.forEach((key) => {
        widths[key] = (space * weights[key]) / totalWeight;
      });
      break;
    }
    constrained.forEach((key) => {
      widths[key] = AIDP_MIN_COLUMN_WIDTH;
      space -= AIDP_MIN_COLUMN_WIDTH;
    });
    remaining = remaining.filter((key) => !constrained.includes(key));
  }
  return widths;
}

/** Move one boundary without changing the total width or unrelated columns. */
export function resizeAidpColumnPair(
  widths: Record<string, number>,
  leftKey: string,
  rightKey: string,
  delta: number
): Record<string, number> {
  const movement = Math.max(
    AIDP_MIN_COLUMN_WIDTH - widths[leftKey],
    Math.min(delta, widths[rightKey] - AIDP_MIN_COLUMN_WIDTH)
  );
  return {
    ...widths,
    [leftKey]: widths[leftKey] + movement,
    [rightKey]: widths[rightKey] - movement,
  };
}
