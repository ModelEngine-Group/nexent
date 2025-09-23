import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"
import { CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined } from '@ant-design/icons' 
import { DOCUMENT_STATUS } from "@/const/knowledgeBase"
import React from 'react'
import log from "@/lib/logger";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

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
      return React.createElement(LoadingOutlined, { style: { color: '#1890ff' } })
    case "available":
      return React.createElement(CheckCircleOutlined, { style: { color: '#52c41a' } })
    case "unavailable":
      return React.createElement(CloseCircleOutlined, { style: { color: '#ff4d4f' } })
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
        icon: React.createElement(LoadingOutlined, { style: { color: '#1890ff' } }),
        color: '#1890ff'
      }
    case "available":
      return {
        icon: React.createElement(CheckCircleOutlined, { style: { color: '#52c41a' } }),
        color: '#52c41a'
      }
    case "unavailable":
      return {
        icon: React.createElement(CloseCircleOutlined, { style: { color: '#ff4d4f' } }),
        color: '#ff4d4f'
      }
    default:
      return {
        icon: null,
        color: '#d9d9d9'
      }
  }
}