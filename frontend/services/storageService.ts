import { API_ENDPOINTS } from './api';
import { StorageUploadResult } from '../types/chat';

import { fetchWithAuth } from '@/lib/auth';
// @ts-ignore
const fetch = fetchWithAuth;

/**
 * Extract object_name from file URL
 * Supports formats like:
 * - http://localhost:3000/nexent/attachments/filename.png
 * - /nexent/attachments/filename.png
 * - attachments/filename.png
 * - s3://nexent/attachments/filename.png
 * Works for all file types: images, videos, documents, etc.
 * @param url File URL (can be image, video, document, or any other file type)
 * @returns object_name or null
 */
export function extractObjectNameFromUrl(url: string): string | null {
  try {
    // Handle s3:// protocol URLs (e.g., s3://nexent/attachments/filename.png)
    if (url.startsWith("s3://")) {
      // Remove s3:// prefix
      const withoutProtocol = url.replace(/^s3:\/\//, "");
      const parts = withoutProtocol.split("/").filter(Boolean);
      
      // Find attachments in path
      const attachmentsIndex = parts.indexOf("attachments");
      if (attachmentsIndex >= 0) {
        return parts.slice(attachmentsIndex).join("/");
      }
      
      // If no attachments found but has bucket and path, return the path after bucket
      if (parts.length > 1) {
        return parts.slice(1).join("/");
      }
      
      // If only one part, return it as object_name
      if (parts.length === 1) {
        return parts[0];
      }
      
      return null;
    }

    // Handle object_name or relative paths directly (e.g. "attachments/xxx.pdf")
    const isHttpUrl = url.startsWith("http://") || url.startsWith("https://");
    if (!isHttpUrl) {
      // Remove leading "/" if present
      const normalized = url.replace(/^\/+/, "");
      if (!normalized) {
        return null;
      }

      const attachmentsIndex = normalized.indexOf("attachments/");
      if (attachmentsIndex >= 0) {
        return normalized.slice(attachmentsIndex);
      }

      // If there is no "attachments" segment but this is a plain path,
      // treat the whole normalized path as object_name
      return normalized;
    }

    // Handle relative URLs
    if (url.startsWith("/")) {
      // Remove leading slash and extract path after /nexent/ or /attachments/
      const parts = url.split("/").filter(Boolean);
      const attachmentsIndex = parts.indexOf("attachments");
      if (attachmentsIndex >= 0) {
        return parts.slice(attachmentsIndex).join("/");
      }
      // If no attachments found, try to find the last part
      if (parts.length > 0) {
        return parts.join("/");
      }
    }

    // Handle full URLs
    const urlObj = new URL(url);
    const pathname = urlObj.pathname;
    const parts = pathname.split("/").filter(Boolean);

    // Find attachments in path
    const attachmentsIndex = parts.indexOf("attachments");
    if (attachmentsIndex >= 0) {
      return parts.slice(attachmentsIndex).join("/");
    }

    // If no attachments found, return the last meaningful part
    if (parts.length > 0) {
      return parts.join("/");
    }

    return null;
  } catch (error) {
    return null;
  }
}

/**
 * Convert image URL to backend API URL
 * @param url Original image URL (can be MinIO URL or local path)
 * @returns Backend API URL for the image
 */
export function convertImageUrlToApiUrl(url: string): string {
  // If URL is an external http/https URL (not backend API), use proxy to avoid CORS and 403 errors
  if (
    (url.startsWith("http://") || url.startsWith("https://")) &&
    !url.includes("/api/file/download/") &&
    !url.includes("/api/image")
  ) {
    // Use backend proxy to fetch external images (avoids CORS and hotlink protection)
    return API_ENDPOINTS.proxy.image(url);
  }
  
  const objectName = extractObjectNameFromUrl(url);
  if (objectName) {
    // Use the same download endpoint with stream mode for images
    return API_ENDPOINTS.storage.file(objectName, "stream");
  }
  // Fallback to original URL if extraction fails
  return url;
}

export const storageService = {
  /**
   * Upload files to storage service
   * @param files List of files to upload
   * @param folder Optional folder path
   * @returns Upload result
   */
  async uploadFiles(
    files: File[],
    folder: string = 'attachments'
  ): Promise<StorageUploadResult> {
    // Create FormData object
    const formData = new FormData();
    
    // Add files
    files.forEach(file => {
      formData.append('files', file);
    });
    
    // Add folder parameter
    formData.append('folder', folder);
    
    // Send request
    const response = await fetch(API_ENDPOINTS.storage.upload, {
      method: 'POST',
      body: formData,
    });
    
    if (!response.ok) {
      throw new Error(`Failed to upload files to Minio: ${response.statusText}`);
    }
    
    return await response.json();
  },
  
  /**
   * Get the URL of a single file
   * @param objectName File object name
   * @returns File URL
   */
  async getFileUrl(objectName: string): Promise<string> {
    const response = await fetch(API_ENDPOINTS.storage.file(objectName));
    
    if (!response.ok) {
      throw new Error(`Failed to get file URL from Minio: ${response.statusText}`);
    }
    
    const data = await response.json();
    return data.url;
  },
  
  /**
   * Download file directly using backend API (faster, browser handles download)
   * @param objectName File object name
   * @param filename Optional filename for download
   * @returns Promise that resolves when download link is opened
   */
  async downloadFile(objectName: string, filename?: string): Promise<void> {
    try {
      // Use direct link download for better performance
      // Browser will handle the download stream directly
      // Pass filename to backend so it can set the correct Content-Disposition header
      const downloadUrl = API_ENDPOINTS.storage.file(objectName, "stream", filename);
      
      // Create download link and trigger download
      // Using direct link allows browser to handle download stream efficiently
      const link = document.createElement("a");
      link.href = downloadUrl;
      // Set download attribute as fallback (browser will use Content-Disposition header if available)
      link.download = filename || objectName.split("/").pop() || "download";
      link.style.display = "none";
      document.body.appendChild(link);
      
      // Trigger download
      link.click();
      
      // Clean up after a short delay to ensure download starts
      setTimeout(() => {
        document.body.removeChild(link);
      }, 100);
    } catch (error) {
      throw new Error(`Failed to download file: ${error instanceof Error ? error.message : String(error)}`);
    }
  },
  
  /**
   * Download file from Datamate knowledge base via HTTP URL
   * @param url HTTP URL of the file to download
   * @param filename Optional filename for download
   * @returns Promise that resolves when download link is opened
   */
  async downloadDatamateFile(options: {
    url?: string;
    baseUrl?: string;
    datasetId?: string;
    fileId?: string;
    filename?: string;
  }): Promise<void> {
    try {
      const downloadUrl = API_ENDPOINTS.storage.datamateDownload(options);
      const link = document.createElement("a");
      link.href = downloadUrl;
      // Only set download attribute when caller explicitly provides a filename.
      // Otherwise, let the browser use the Content-Disposition header from backend,
      // which already encodes the correct filename.
      if (options.filename) {
        link.download = options.filename;
      }
      link.style.display = "none";
      document.body.appendChild(link);
      link.click();
      setTimeout(() => {
        document.body.removeChild(link);
      }, 100);
    } catch (error) {
      throw new Error(`Failed to download datamate file: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
}; 