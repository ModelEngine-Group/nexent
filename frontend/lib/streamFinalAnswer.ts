/** Remove only an exact final-answer echo at the end of a streamed model block. */
export function stripStreamedFinalAnswerEcho(
  streamed: string,
  finalAnswer: string
): string | null {
  if (!finalAnswer.trim() || !streamed.endsWith(finalAnswer)) return null;
  return streamed.slice(0, -finalAnswer.length);
}
