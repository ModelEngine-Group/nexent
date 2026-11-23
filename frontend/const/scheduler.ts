/**
 * Scheduler frequency constants
 * Options should be fetched from backend API: /api/indices/summary_frequency_options
 */

export interface FrequencyOption {
  value: string;
  label: string;
}

export interface FrequencyOptionsResponse {
  options: FrequencyOption[];
  valid_values: (string | null)[];
}

// API endpoint to fetch frequency options
import { withBasePath } from "@/lib/basePath";

export const SUMMARY_FREQUENCY_OPTIONS_API = withBasePath("/api/indices/summary_frequency_options");

// Type for summary frequency
export type SummaryFrequency = string | null;