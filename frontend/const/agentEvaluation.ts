/** Runtime fallbacks for evaluation-set upload configuration. */
export const DEFAULT_EVALUATION_SET_FILE_SIZE_MB = 20;

export const evaluationSetFileSizeToBytes = (sizeMb: number): number =>
  sizeMb * 1024 * 1024;
