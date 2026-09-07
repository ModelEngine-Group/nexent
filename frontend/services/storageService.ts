import { API_BASE_URL, API_ENDPOINTS } from "./api";
import { StorageUploadResult } from "../types/chat";
import { arrayBufferToBase64 } from "@/lib/agentImportUtils";
import { withBasePath } from "@/lib/basePath";
import log from "@/lib/logger";

import { fetchWithAuth } from "@/lib/auth";
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
      const storageIndex = parts.findIndex(
        (part) => part === "attachments" || part === "knowledge_base"
      );
      if (storageIndex >= 0) {
        return parts.slice(storageIndex).join("/");
      }

      // If no storage prefix was found but has bucket and path, return the path after bucket
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

      const storageIndex = ["attachments/", "knowledge_base/"].reduce(
        (firstIndex, prefix) => {
          const index = normalized.indexOf(prefix);
          return index >= 0 && (firstIndex < 0 || index < firstIndex)
            ? index
            : firstIndex;
        },
        -1
      );
      if (storageIndex >= 0) {
        return normalized.slice(storageIndex);
      }

      // If there is no storage prefix but this is a plain path,
      // treat the whole normalized path as object_name
      return normalized;
    }

    // Handle relative URLs
    if (url.startsWith("/")) {
      // Remove leading slash and extract path after /nexent/ or /attachments/
      const parts = url.split("/").filter(Boolean);
      const storageIndex = parts.findIndex(
        (part) => part === "attachments" || part === "knowledge_base"
      );
      if (storageIndex >= 0) {
        return parts.slice(storageIndex).join("/");
      }
      // If no storage prefix was found, try to find the last part
      if (parts.length > 0) {
        return parts.join("/");
      }
    }

    // Handle full URLs
    const urlObj = new URL(url);
    const pathname = urlObj.pathname;
    const parts = pathname.split("/").filter(Boolean);

    const storageIndex = parts.findIndex(
      (part) => part === "attachments" || part === "knowledge_base"
    );
    if (storageIndex >= 0) {
      return parts.slice(storageIndex).join("/");
    }

    // If no storage prefix was found, return the last meaningful part
    if (parts.length > 0) {
      return parts.join("/");
    }

    return null;
  } catch (error) {
    return null;
  }
}

export function isLocalStorageObjectUrl(url: string | undefined): boolean {
  if (!url) return false;
  if (url.startsWith("s3://")) return true;

  const objectName = extractObjectNameFromUrl(url);
  return Boolean(
    objectName && /(^|\/)(knowledge_base|attachments)\//.test(objectName)
  );
}

export function getLocalFilePreviewUrl(
  url: string | undefined,
  filename?: string,
  objectName?: string
): string | undefined {
  const resolvedObjectName =
    objectName || (url ? extractObjectNameFromUrl(url) : null);
  if (
    !resolvedObjectName ||
    !isLocalStorageObjectUrl(url ?? resolvedObjectName)
  ) {
    return undefined;
  }

  return API_ENDPOINTS.storage.preview(resolvedObjectName, filename);
}

/**
 * Convert a permanent local-storage reference into an authenticated backend
 * download URL. The permanent reference (normally s3://bucket/object_name) is
 * safe to persist in Markdown; the browser-facing URL is derived at render
 * time and therefore never contains an expiring MinIO signature.
 */
export function getLocalFileDownloadUrl(
  url: string | undefined,
  filename?: string
): string | undefined {
  if (!url || !isLocalStorageObjectUrl(url)) return undefined;

  const objectName = extractObjectNameFromUrl(url);
  if (!objectName) return undefined;

  return API_ENDPOINTS.storage.file(objectName, "stream", filename);
}

/**
 * Convert image URL to backend API URL
 * @param url Original image URL (can be MinIO URL or local path)
 * @returns Backend API URL for the image
 */
export async function fetchImageBlob(url: string): Promise<Blob> {
  const apiUrl = convertImageUrlToApiUrl(url);
  log.info(`[fetchImageBlob] input=${url}, apiUrl=${apiUrl}`);
  const response = await fetch(apiUrl);
  log.info(
    `[fetchImageBlob] status=${response.status}, contentType=${response.headers.get("content-type")}`
  );
  if (!response.ok) {
    throw new Error(
      `Failed to fetch image: ${response.status} ${response.statusText}`
    );
  }
  const contentType = response.headers.get("content-type") || "";
  // Image service returns JSON error body with HTTP 200 on proxy failure;
  // must detect this or FileReader will try to render JSON as an image.
  if (contentType.startsWith("application/json")) {
    const body = await response.text();
    log.error(
      `[fetchImageBlob] got JSON instead of image: ${body.slice(0, 300)}`
    );
    try {
      const json = JSON.parse(body);
      throw new Error(
        json?.error || `Image proxy returned JSON: ${body.slice(0, 200)}`
      );
    } catch (e) {
      if (e instanceof SyntaxError) {
        throw new Error(
          `Image proxy returned non-image JSON: ${body.slice(0, 200)}`
        );
      }
      throw e;
    }
  }
  return response.blob();
}

export function convertImageUrlToApiUrl(url: string): string {
  const isHttpUrl = url.startsWith("http://") || url.startsWith("https://");

  if (url.startsWith("/api/ind-aidp/images/")) {
    return withBasePath(url);
  }

  if (url.startsWith(`${API_BASE_URL}/share/`)) {
    return url;
  }

  // Backend share URLs do not include the frontend base path.
  if (url.startsWith("/api/share/")) {
    return withBasePath(url);
  }

  // For localhost URLs in development, return original URL directly to avoid proxy issues
  if (isHttpUrl && /localhost|127\.0\.0\.1/i.test(url)) {
    return url;
  }

  // For external http/https URLs, use proxy to avoid CORS issues
  if (
    isHttpUrl &&
    !url.includes(`${API_BASE_URL}/file/download/`) &&
    !url.includes(`${API_BASE_URL}/image`)
  ) {
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

const fetchBase64ViaStorage = async (objectName: string) => {
  const response = await fetch(
    API_ENDPOINTS.storage.file(objectName, "base64")
  );
  if (!response.ok) {
    throw new Error(`Failed to resolve S3 URL via storage: ${response.status}`);
  }

  const data = await response.json();
  if (!data?.success || !data?.base64) {
    throw new Error(data?.error || "Storage response missing base64 content");
  }

  const contentType = data.content_type || "application/octet-stream";
  return { base64: data.base64 as string, contentType };
};

// Cache for S3 URL to data URL resolution to avoid duplicate network requests
const s3ResolutionCache = new Map<string, Promise<string | null>>();

// Internal helper: for s3:// URLs, resolve directly via storage download endpoint.
async function resolveS3UrlToDataUrlInternal(
  url: string
): Promise<string | null> {
  const objectName = extractObjectNameFromUrl(url);
  if (!objectName) {
    return null;
  }

  const { base64, contentType } = await fetchBase64ViaStorage(objectName);
  return `data:${contentType};base64,${base64}`;
}

export async function resolveS3UrlToDataUrl(
  url: string
): Promise<string | null> {
  if (!url || !url.startsWith("s3://")) {
    return null;
  }

  const cached = s3ResolutionCache.get(url);
  if (cached) {
    return cached;
  }

  const promise = resolveS3UrlToDataUrlInternal(url).catch((error) => {
    // Remove from cache on failure so that future attempts can retry.
    s3ResolutionCache.delete(url);
    throw error;
  });

  s3ResolutionCache.set(url, promise);
  return promise;
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
    folder: string = "attachments"
  ): Promise<StorageUploadResult> {
    // Create FormData object
    const formData = new FormData();

    // Add files
    files.forEach((file) => {
      formData.append("files", file);
    });

    // Add folder parameter
    formData.append("folder", folder);

    // Send request
    const response = await fetch(API_ENDPOINTS.storage.upload, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      throw new Error(
        `Failed to upload files to Minio: ${response.statusText}`
      );
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
      throw new Error(
        `Failed to get file URL from Minio: ${response.statusText}`
      );
    }

    const data = await response.json();
    return data.url;
  },

  /**
   * Get preview URL for a file (supports PDF, Office, Images, Text)
   * @param objectName File object name in storage
   * @param filename Optional filename for Content-Disposition header
   * @returns Preview URL
   */
  getPreviewUrl(objectName: string, filename?: string): string {
    return API_ENDPOINTS.storage.preview(objectName, filename);
  },

  /**
   * Download file directly using backend API (faster, browser handles download)
   * @param objectName File object name
   * @param filename Optional filename for download
   * @returns Promise that resolves when download link is opened
   */
  async downloadFile(objectName: string, filename?: string): Promise<void> {
    try {
      const downloadUrl = API_ENDPOINTS.storage.file(
        objectName,
        "stream",
        filename
      );
      const link = document.createElement("a");
      link.href = downloadUrl;
      link.download = filename || objectName.split("/").pop() || "download";
      link.style.display = "none";
      document.body.appendChild(link);
      link.click();
      setTimeout(() => {
        document.body.removeChild(link);
      }, 100);
    } catch (error) {
      throw new Error(
        `Failed to download file: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  },

  async downloadFileWithAuth(
    objectName: string,
    filename?: string
  ): Promise<void> {
    try {
      const response = await fetch(
        API_ENDPOINTS.storage.file(objectName, "stream", filename)
      );
      if (!response.ok) {
        throw new Error(`File download failed: ${response.status}`);
      }

      const blobUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = filename || objectName.split("/").pop() || "download";
      link.style.display = "none";
      document.body.appendChild(link);
      link.click();
      setTimeout(() => {
        document.body.removeChild(link);
        URL.revokeObjectURL(blobUrl);
      }, 100);
    } catch (error) {
      throw new Error(
        `Failed to download file: ${error instanceof Error ? error.message : String(error)}`
      );
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
      throw new Error(
        `Failed to download datamate file: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  },
};
