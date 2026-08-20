export const getDisplayWidth = (value: string = "") =>
  Array.from(value).reduce(
    (width, char) => width + (/[^\u0000-\u00ff]/.test(char) ? 2 : 1),
    0
  );
