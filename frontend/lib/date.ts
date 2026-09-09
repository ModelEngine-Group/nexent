import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";

dayjs.extend(utc);
dayjs.extend(timezone);

type DateInput = string | number | Date | null | undefined;

// Parse input that may be:
// - number (ms timestamp) → dayjs(num), auto-local
// - Date object → dayjs(date), auto-local
// - ISO string with timezone (Z / +08:00) → dayjs(str), auto-local
// - string without timezone → assume server stored UTC, then convert to local
function parseDate(input: DateInput): dayjs.Dayjs | null {
  if (input === null || input === undefined || input === "") return null;
  if (typeof input === "number") return dayjs(input);
  if (input instanceof Date) return dayjs(input);
  const str = String(input).trim();
  // Has timezone suffix: Z, +HH:MM, +HHMM, -HH:MM
  if (/[Zz]$|[+-]\d{2}:?\d{2}$/.test(str)) {
    return dayjs(str);
  }
  // No timezone info → assume server stored UTC
  return dayjs.utc(str);
}

// Shared helper: parse, validate, then format in the user's local timezone.
function formatLocal(date: DateInput, format: string): string | undefined {
  const d = parseDate(date);
  if (!d?.isValid()) return undefined;
  return d.local().format(format);
}

/**
 * Format a date to YYYY-MM-DD in the user's local timezone.
 * Accepts ms timestamp, Date object, ISO string (with/without timezone).
 * Strings without timezone info are assumed to be UTC.
 */
export function formatDate(date: DateInput): string | undefined {
  return formatLocal(date, "YYYY-MM-DD");
}

/**
 * Format a date to YYYY-MM-DD HH:mm:ss in the user's local timezone.
 * Accepts ms timestamp, Date object, ISO string (with/without timezone).
 * Strings without timezone info are assumed to be UTC.
 */
export function formatDateTime(date: DateInput): string | undefined {
  return formatLocal(date, "YYYY-MM-DD HH:mm:ss");
}

/**
 * Format a date with locale-aware medium date+time in the user's local
 * timezone. Replaces Intl.DateTimeFormat usage.
 */
export function formatDateTimeLocale(date: DateInput, locale?: string): string {
  const isZh = locale?.startsWith("zh");
  return formatLocal(date, isZh ? "YYYY-MM-DD HH:mm" : "MMM D, YYYY h:mm A") ?? "-";
}

/**
 * Format a date to YYYY-MM-DD, falling back to the string representation
 * of the input when parsing fails. Convenience for components that need
 * a non-undefined string return.
 */
export function formatDateOrFallback(date: DateInput): string {
  return formatDate(date) ?? String(date ?? "");
}
