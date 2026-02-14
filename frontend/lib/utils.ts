import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"
import { CircleCheck, XCircle, LoaderCircle } from "lucide-react"
import { DOCUMENT_STATUS } from "@/const/knowledgeBase"
import React from 'react'
import log from "@/lib/logger";
import i18n from "@/app/i18n";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Check if current language is Chinese
 * @returns true if current language is Chinese (zh or zh-CN)
 */
export const isZhLocale = (): boolean => {
  if (typeof window === 'undefined') {
    return false; // Default to English on server side
  }
  // Use i18next language setting, fallback to navigator.language
  const lang = i18n.language || navigator.language || (window.navigator as any).language;
  return lang === 'zh' || lang === 'zh-CN' || lang.startsWith('zh');
};

/**
 * Get localized description - returns Chinese description if available and locale is Chinese
 * @param description English description
 * @param description_zh Chinese description (optional)
 * @returns The appropriate description based on current locale
 */
export const getLocalizedDescription = (
  description: string | undefined,
  description_zh: string | undefined
): string => {
  if (isZhLocale() && description_zh) {
    return description_zh;
  }
  return description || '';
};

/**
 * Get bilingual description object for UI components
 * @param description English description
 * @param description_zh Chinese description (optional)
 * @returns Object with both descriptions
 */
export const getBilingualDescription = (
  description: string | undefined,
  description_zh: string | undefined
): { description: string; description_zh?: string } => {
  return {
    description: description || '',
    ...(description_zh && { description_zh }),
  };
};

// Get status priority
function getStatusPriority(status: string): number {
  switch (status) {
    case DOCUMENT_STATUS.WAIT_FOR_PROCESSING: // Waiting for processing
      return 1;
    case DOCUMENT_STATUS.PROCESSING: // Processing
      return 2;
    case DOCUMENT_STATUS.WAIT_FOR_FORWARDING: // Waiting for forwarding
      return 3;
    case DOCUMENT_STATUS.FORWARDING: // Forwarding
      return 4;
    case DOCUMENT_STATUS.COMPLETED: // Processing completed
      return 5;
    case DOCUMENT_STATUS.PROCESS_FAILED: // Processing failed
      return 6;
    case DOCUMENT_STATUS.FORWARD_FAILED: // Forwarding failed
      return 7;
    default:
      return 8;
  }
}

// Sort by status and date
export function sortByStatusAndDate<T extends { status: string; create_time: string }>(items: T[]): T[] {
  return [...items].sort((a, b) => {
    // First sort by status priority
    const statusPriorityA = getStatusPriority(a.status);
    const statusPriorityB = getStatusPriority(b.status);
    
    if (statusPriorityA !== statusPriorityB) {
      return statusPriorityA - statusPriorityB;
    }
    
    // When the status is the same, sort by date (from new to old)
    const dateA = new Date(a.create_time).getTime();
    const dateB = new Date(b.create_time).getTime();
    return dateB - dateA;
  });
}

// Format file size
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

// Format date
export function formatDate(dateString: string): string {
  try {
    const date = new Date(dateString)
    if (isNaN(date.getTime())) {
      return ""
    }
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    
    return `${year}-${month}-${day}`;
  } catch (error) {
    return ""
  }
}

// Format URL display
// TODO: Type should not be defined here
export interface SearchResultUrl {
  source_type?: string;
  url?: string;
  filename?: string;
}

export function formatUrl(result: SearchResultUrl): string {
  try {
    if (!result.source_type) return ""
    
    if (result.source_type === "url") {
      if (!result.url || result.url === "#") return ""
      return result.url.replace(/(^\w+:|^)\/\//, '').split('/')[0]
    } else if (result.source_type === "file") {
      if (!result.filename) return ""
      return result.filename
    }
    return ""
  } catch (error) {
    return ""
  }
}

/**
 * URL parameter retrieval utility function
 * @param paramName Parameter name
 * @param defaultValue Default value
 * @param transform Transform function (optional)
 * @returns Parameter value
 */
export function getUrlParam<T>(
  paramName: string, 
  defaultValue: T, 
  transform?: (value: string) => T
): T {
  if (typeof window === 'undefined') return defaultValue
  
  try {
    const url = new URL(window.location.href)
    const paramValue = url.searchParams.get(paramName)
    
    if (paramValue === null) return defaultValue
    
    if (transform) {
      return transform(paramValue)
    }
    
    return paramValue as unknown as T
  } catch (error) {
    log.warn(`Failed to get URL parameter ${paramName}:`, error)
    return defaultValue
  }
}


  /**
   * Convert backend type to frontend type
   * @param backendType Backend type name
   * @returns Corresponding frontend type
   */
  export const convertParamType = (backendType: string): 'string' | 'number' | 'boolean' | 'array' | 'object' | 'Optional' => {
    switch (backendType) {
      case 'string':
        return 'string';
      case 'integer':
      case 'float':
        return 'number';
      case 'boolean':
        return 'boolean';
      case 'array':
        return 'array';
      case 'object':
        return 'object';
      case 'Optional':
        return 'string'; 
      default:
        log.warn(`Unknown type: ${backendType}, using string as default type`);
        return 'string';
    }
  };

// Connectivity status utilities
export type ConnectivityStatusType = "checking" | "available" | "unavailable" | null;

// Get the connectivity status icon
export const getConnectivityIcon = (status: ConnectivityStatusType): React.ReactNode => {
  switch (status) {
    case "checking":
      return React.createElement(LoaderCircle, { className: 'animate-spin', color: '#1890ff', size: 16 })
    case "available":
      return React.createElement(CircleCheck, { color: '#52c41a', size: 16 })
    case "unavailable":
      return React.createElement(XCircle, { color: '#ff4d4f', size: 16 })
    default:
      return null
  }
}

// Get the connectivity status color
export const getConnectivityColor = (status: ConnectivityStatusType): string => {
  switch (status) {
    case "checking":
      return '#1890ff'
    case "available":
      return '#52c41a'
    case "unavailable":
      return '#ff4d4f'
    default:
      return '#d9d9d9'
  }
}

export type ConnectivityMeta = {
  icon: React.ReactNode
  color: string
}

export const getConnectivityMeta = (status: ConnectivityStatusType): ConnectivityMeta => {
  switch (status) {
    case "checking":
      return {
        icon: React.createElement(LoaderCircle, { className: 'animate-spin', color: '#1890ff', size: 16 }),
        color: '#1890ff'
      }
    case "available":
      return {
        icon: React.createElement(CircleCheck, { color: '#52c41a', size: 16 }),
        color: '#52c41a'
      }
    case "unavailable":
      return {
        icon: React.createElement(XCircle, { color: '#ff4d4f', size: 16 }),
        color: '#ff4d4f'
      }
    default:
      return {
        icon: null,
        color: '#d9d9d9'
      }
  }
}

/**
 * Format search score as percentage string
 * @param score Search score (0-1 range)
 * @returns Formatted percentage string with one decimal place (e.g., "95.5%")
 */
export function formatScoreAsPercentage(score: number): string {
  if (typeof score !== 'number' || isNaN(score)) {
    return '0.0%';
  }
  const percentage = score * 100;
  return `${percentage.toFixed(1)}%`;
}

/**
 * Get color for search score tag
 * @param score Search score (0-1 range)
 * @returns Color hex string - default gray for scores < 90%, green gradient for scores >= 90%
 */
export function getScoreColor(score: number): string {
  if (typeof score !== 'number' || isNaN(score)) {
    return '#d9d9d9'; // Default gray
  }
  
  const percentage = score * 100;
  
  // Scores below 90% use default gray
  if (percentage < 90) {
    return '#d9d9d9';
  }
  
  // Scores 90% and above: gradient from light green to dark green
  // Map 90-100% to color range: #A8E6B2 (light green) to #39C651 (dark green)
  const normalized = (percentage - 90) / 10; // 0 to 1 for 90-100%
  
  // Interpolate between light green (#95de64) and dark green (#52c41a)
  const r1 = 0xa8, g1 = 0xe6, b1 = 0xb2; // Light green
  const r2 = 0x39, g2 = 0xc6, b2 = 0x51; // Dark green
  
  const r = Math.round(r1 + (r2 - r1) * normalized);
  const g = Math.round(g1 + (g2 - g1) * normalized);
  const b = Math.round(b1 + (b2 - b1) * normalized);
  
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
}