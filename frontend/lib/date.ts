import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";

dayjs.extend(utc);
dayjs.extend(timezone);

// Parse input that may be:
// - number (ms timestamp) → dayjs(num), auto-local
// - Date object → dayjs(date), auto-local
// - ISO string with timezone (Z / +08:00) → dayjs(str), auto-local
// - string without timezone → assume server stored UTC, then convert to local
function parseDate(
  input: string | number | Date | null | undefined
): dayjs.Dayjs | null {
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

/**
 * Format a date to YYYY-MM-DD in the user's local timezone.
 * Accepts ms timestamp, Date object, ISO string (with/without timezone).
 * Strings without timezone info are assumed to be UTC.
 */
export function formatDate(
  date: string | number | Date | null | undefined
): string | undefined {
  const d = parseDate(date);
  if (!d || !d.isValid()) return undefined;
  return d.local().format("YYYY-MM-DD");
}

/**
 * Format a date to YYYY-MM-DD HH:mm:ss in the user's local timezone.
 * Accepts ms timestamp, Date object, ISO string (with/without timezone).
 * Strings without timezone info are assumed to be UTC.
 */
export function formatDateTime(
  date: string | number | Date | null | undefined
): string | undefined {
  const d = parseDate(date);
  if (!d || !d.isValid()) return undefined;
  return d.local().format("YYYY-MM-DD HH:mm:ss");
}

/**
 * Format a date with locale-aware medium date+time in the user's local
 * timezone. Replaces Intl.DateTimeFormat usage.
 */
export function formatDateTimeLocale(
  date: string | number | Date | null | undefined,
  locale?: string
): string {
  const d = parseDate(date);
  if (!d || !d.isValid()) return "-";
  const isZh = locale?.startsWith("zh");
  return d.local().format(isZh ? "YYYY-MM-DD HH:mm" : "MMM D, YYYY h:mm A");
}
