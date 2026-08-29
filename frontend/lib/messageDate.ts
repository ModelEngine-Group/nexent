export type MessageDateInput = Date | number | null | undefined;

const isValidDate = (date: Date): boolean => Number.isFinite(date.getTime());

export const toMessageCreatedAt = (
  createTime: number | null | undefined
): Date | undefined => {
  if (!Number.isFinite(createTime) || !createTime || createTime <= 0) {
    return undefined;
  }

  const date = new Date(createTime);
  return isValidDate(date) ? date : undefined;
};

const asValidDate = (input: MessageDateInput): Date | undefined => {
  if (input instanceof Date) return isValidDate(input) ? input : undefined;
  return toMessageCreatedAt(input);
};

export const formatMessageTime = (
  input: MessageDateInput
): string | undefined => {
  const date = asValidDate(input);
  if (!date) return undefined;

  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${hours}:${minutes}`;
};

export const formatMessageDate = (
  input: MessageDateInput,
  locale?: string
): string | undefined => {
  const date = asValidDate(input);
  if (!date) return undefined;

  return new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(date);
};

const isSameLocalDay = (left: Date, right: Date): boolean =>
  left.getFullYear() === right.getFullYear() &&
  left.getMonth() === right.getMonth() &&
  left.getDate() === right.getDate();

export const shouldShowDateSeparator = (
  current: MessageDateInput,
  previous: MessageDateInput
): boolean => {
  const currentDate = asValidDate(current);
  if (!currentDate) return false;

  const previousDate = asValidDate(previous);
  return !previousDate || !isSameLocalDay(currentDate, previousDate);
};
