/**
 * Format a date string or Date object to YYYY-MM-DD format
 * @param date - Date string (ISO format or other formats) or Date object
 * @returns Formatted date string in YYYY-MM-DD format, or undefined if input is invalid
 */
export function formatDate(date: string | Date | null | undefined): string | undefined {
  if (!date) {
    return undefined;
  }

  const dateObj = new Date(date);
  if (isNaN(dateObj.getTime())) {
    return undefined;
  }

  const year = dateObj.getFullYear();
  const month = String(dateObj.getMonth() + 1).padStart(2, "0");
  const day = String(dateObj.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}
