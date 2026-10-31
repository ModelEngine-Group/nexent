// Terminal/Jupyter output may contain console styling sequences. Browsers do
// not interpret them, so leaving them in chat text exposes unreadable markers
// such as "[31m" to users.
export function stripAnsiControlSequences(value: string): string {
  return value.replace(
    // eslint-disable-next-line no-control-regex
    /(?:\u001b\[[0-?]*[ -/]*[@-~]|\u001b\][^\u0007\u001b]*(?:\u0007|\u001b\\)|\u001b[@-_]|\u009b[0-?]*[ -/]*[@-~])/g,
    ""
  );
}
