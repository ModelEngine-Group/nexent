import React, { useState, useEffect, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { ExternalLink, Database, X, Server } from "lucide-react";

import { ImageItem, ChatRightPanelProps, SearchResult } from "@/types/chat";
import { formatDate, formatUrl } from "@/lib/utils";
import {
  convertImageUrlToApiUrl,
  extractObjectNameFromUrl,
  storageService,
} from "@/services/storageService";
import { message, Button } from "antd";
import log from "@/lib/logger";
import { useConfig } from "@/hooks/useConfig";
import type { AppConfig } from "@/types/modelConfig";

interface SearchResultItemProps {
  result: SearchResult;
  t: any; // TFunction from react-i18next
  appConfig: AppConfig | null;
}

// Search result item component - moved to module scope to prevent re-creation on each render
function SearchResultItem({ result, t, appConfig }: SearchResultItemProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const title = result.title || t("chatRightPanel.unknownTitle");
  const url = result.url || "#";
  const text = result.text || t("chatRightPanel.noContentDescription");
  const published_date = result.published_date || "";
  const source_type = result.source_type || "url";
  const filename = result.filename || result.title || "";
  const searchType = result.search_type || "";
  const isKnowledgeResult =
    source_type === "file" ||
    source_type === "datamate" ||
    source_type === "aidp" ||
    searchType === "aidp_search";
  const datamateDatasetId =
    result.score_details?.datamate_dataset_id ||
    result.score_details?.dataset_id;
  const datamateFileId =
    result.score_details?.datamate_file_id || result.score_details?.file_id;
  const datamateBaseUrl =
    result.score_details?.datamate_base_url ||
    result.score_details?.datamate_baseUrl ||
    result.score_details?.base_url;

  const resolveSourceLabel = (): string => {
    if (source_type === "datamate") {
      return t("chatRightPanel.source.datamate", "Source: Datamate");
    }
    if (source_type === "aidp" || searchType === "aidp_search") {
      return t("chatRightPanel.source.aidp", "Source: AIDP");
    }
    if (source_type === "file") {
      return t("chatRightPanel.source.nexent", "Source: Nexent");
    }
    return "";
  };

  const downloadDatamateFile = async () => {
    if (!appConfig?.modelEngineEnabled) {
      message.error(
        "DataMate download not available: ModelEngine is not enabled"
      );
      return;
    }
    if (!datamateDatasetId || !datamateFileId || !datamateBaseUrl) {
      if (!url || url === "#") {
        message.error(
          t(
            "chatRightPanel.fileDownloadError",
            "Missing Datamate dataset or file information"
          )
        );
        return;
      }
    }
    await storageService.downloadDatamateFile({
      url: url !== "#" ? url : undefined,
      baseUrl: datamateBaseUrl,
      datasetId: datamateDatasetId,
      fileId: datamateFileId,
      filename: filename || undefined,
    });
    message.success(
      t("chatRightPanel.fileDownloadSuccess", "File download started")
    );
  };

  const downloadObjectFile = async () => {
    if (result.download_url) {
      const link = document.createElement("a");
      link.href = result.download_url;
      link.download = filename || "download";
      link.click();
      message.success(
        t("chatRightPanel.fileDownloadSuccess", "File download started")
      );
      return;
    }

    let objectName: string | undefined;
    if (result.object_name) {
      objectName = result.object_name;
    } else if (url && url !== "#") {
      objectName = extractObjectNameFromUrl(url) || undefined;
    }
    if (!objectName) {
      message.error(
        t(
          "chatRightPanel.fileDownloadError",
          "Cannot determine file object name"
        )
      );
      return;
    }
    await storageService.downloadFile(objectName, filename || "download");
    message.success(
      t("chatRightPanel.fileDownloadSuccess", "File download started")
    );
  };

  // Handle file download
  const handleFileDownload = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();

    // Standard external-KB adapter path: fetch a presigned download URL
    // lazily from the spec endpoint
    // GET /adapters/{adapter_id}/knowledge-bases/{kb_id}/documents/{doc_id}/download-url
    if (
      source_type === "external" &&
      typeof result?.adapter_id === "number" &&
      result?.knowledge_base_id &&
      result?.document_id
    ) {
      setIsDownloading(true);
      try {
        const { unifiedKBService } = await import(
          "@/services/unifiedKBService"
        );
        const resp = await unifiedKBService.getDocumentDownloadUrl(
          result.adapter_id,
          result.knowledge_base_id,
          result.document_id
        );
        const downloadUrl = resp?.download_url;
        if (!downloadUrl) {
          message.error(
            t(
              "chatRightPanel.fileDownloadError",
              "Failed to obtain download URL for this document"
            )
          );
          return;
        }
        const link = document.createElement("a");
        link.href = downloadUrl;
        link.download = resp?.filename || filename || "download";
        link.click();
        message.success(
          t("chatRightPanel.fileDownloadSuccess", "File download started")
        );
      } catch (error) {
        log.error("Failed to fetch download URL via spec endpoint:", error);
        message.error(
          t(
            "chatRightPanel.fileDownloadError",
            "Failed to download file. Please try again."
          )
        );
      } finally {
        setIsDownloading(false);
      }
      return;
    }

    if (!filename && !url) {
      message.error(
        t("chatRightPanel.fileDownloadError", "File name or URL is missing")
      );
      return;
    }

    setIsDownloading(true);
    try {
      if (source_type === "datamate") {
        await downloadDatamateFile();
        return;
      }
      await downloadObjectFile();
    } catch (error) {
      log.error("Failed to download file:", error);
      message.error(
        t(
          "chatRightPanel.fileDownloadError",
          "Failed to download file. Please try again."
        )
      );
    } finally {
      setIsDownloading(false);
    }
  };

  const titleStyle = {
    display: "-webkit-box",
    WebkitLineClamp: 2,
    WebkitBoxOrient: "vertical" as const,
    overflow: "hidden" as const,
    wordBreak: "break-word" as const,
  };

  const titleContent = isDownloading ? (
    <span className="inline-flex items-center gap-1">
      <span className="animate-spin">⏳</span>
      {t("chatRightPanel.downloading", "Downloading...")}
    </span>
  ) : (
    title
  );

  let titleNode: React.ReactNode;
  if (source_type === "url") {
    titleNode = (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="font-medium text-blue-600 hover:underline block text-base"
        style={titleStyle}
        title={title}
      >
        {title}
      </a>
    );
  } else if (isKnowledgeResult) {
    titleNode = (
      <a
        href="#"
        onClick={handleFileDownload}
        className="font-medium text-blue-600 hover:underline block text-base cursor-pointer"
        style={titleStyle}
        title={title}
      >
        {titleContent}
      </a>
    );
  } else {
    titleNode = (
      <div className="font-medium text-base" style={titleStyle} title={title}>
        {title}
      </div>
    );
  }

  return (
    <div className="p-3 rounded-lg border border-gray-200 text-xs hover:bg-gray-50 transition-colors overflow-hidden">
      <div className="flex flex-col">
        <div>
          {titleNode}

          {published_date && (
            <div className="text-gray-500 mt-1 text-sm">
              {formatDate(published_date)}
            </div>
          )}
        </div>

        <div>
          <p
            className={`text-gray-700 mt-1 text-sm ${
              isExpanded ? "" : "line-clamp-3"
            }`}
          >
            {text}
          </p>
        </div>

        <div className="mt-2 text-sm flex justify-between items-center">
          <div
            className="flex flex-col overflow-hidden"
            style={{ flex: 1, minWidth: 0 }}
          >
            {isKnowledgeResult ? (
              <>
                <div className="flex items-center min-w-0">
                  <div className="w-3 h-3 flex-shrink-0 mr-1">
                    <Database className="w-full h-full" />
                  </div>
                  <a
                    href="#"
                    onClick={handleFileDownload}
                    className="text-blue-600 hover:underline truncate cursor-pointer"
                    style={{
                      maxWidth: "75%",
                      display: "inline-block",
                    }}
                    title={formatUrl(result)}
                  >
                    {filename || formatUrl(result)}
                  </a>
                </div>
                <div className="flex items-center mt-0.5 min-w-0">
                  <div className="w-3 h-3 flex-shrink-0 mr-1">
                    <Server className="w-full h-full" />
                  </div>
                  <div className="text-xs text-gray-500">
                    {resolveSourceLabel()}
                  </div>
                </div>
              </>
            ) : (
              <div className="flex items-center min-w-0">
                <div className="w-3 h-3 flex-shrink-0 mr-1">
                  <ExternalLink className="w-full h-full" />
                </div>
                <span
                  className="text-gray-500 truncate"
                  style={{
                    maxWidth: "75%",
                    display: "inline-block",
                  }}
                  title={formatUrl(result)}
                >
                  {formatUrl(result)}
                </span>
              </div>
            )}
          </div>

          {text.length > 150 && (
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className="text-sm text-gray-500 hover:text-gray-700 flex-shrink-0 ml-2 transition-colors"
            >
              {isExpanded
                ? t("chatRightPanel.collapse")
                : t("chatRightPanel.expand")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export function ChatRightPanel({
  messages,
  onImageError,
  maxInitialImages = 4,
  isVisible = false,
  toggleRightPanel,
  selectedMessageId,
}: ChatRightPanelProps) {
  const { t } = useTranslation("common");
  const { appConfig } = useConfig();
  const [expandedImages, setExpandedImages] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [processedImages, setProcessedImages] = useState<string[]>([]);
  const [viewingImage, setViewingImage] = useState<string | null>(null);
  const [imageData, setImageData] = useState<Record<string, ImageItem>>({});
  const [activeTab, setActiveTab] = useState<string>("sources");

  // Reference to prevent duplicate loading
  const loadingImages = useRef<Set<string>>(new Set());

  // Get the currently selected message
  const currentMessage = messages.find((msg) => msg.id === selectedMessageId);

  // Handle image load failure
  const handleImageLoadFail = useCallback(
    (imageUrl: string) => {
      // Mark image load failure
      setImageData((prev) => ({
        ...prev,
        [imageUrl]: {
          ...(prev[imageUrl] || {}),
          error: t("chatRightPanel.imageLoadFailed"),
          isLoading: false,
        },
      }));

      // Remove from the processed image list
      setProcessedImages((prev) => prev.filter((url) => url !== imageUrl));

      // Call the error handling function
      onImageError(imageUrl);
    },
    [onImageError]
  );

  // Load image - wrapped in useCallback to ensure fresh state references
  // NOTE: does NOT depend on imageData to avoid stale-closure issues
  const loadImage = useCallback(
    async (imageUrl: string) => {
      // Read current state inside the async function to avoid stale closure
      const currentState = imageData;

      // If it is already loaded with data, return directly
      if (
        currentState[imageUrl]?.base64Data &&
        !currentState[imageUrl]?.isLoading
      ) {
        return Promise.resolve();
      }

      // If it is loading, prevent duplicate requests
      if (loadingImages.current.has(imageUrl)) {
        return Promise.resolve();
      }

      // Mark as loading
      loadingImages.current.add(imageUrl);

      // Get the current load attempts (from captured state)
      const currentAttempts = currentState[imageUrl]?.loadAttempts || 0;

      // If the number of attempts is too high, do not continue to try
      if (currentAttempts >= 3) {
        handleImageLoadFail(imageUrl);
        loadingImages.current.delete(imageUrl);
        return Promise.resolve();
      }

      // Mark as loading
      setImageData((prev) => ({
        ...prev,
        [imageUrl]: {
          base64Data: "",
          contentType: "image/jpeg",
          isLoading: true,
          loadAttempts: currentAttempts + 1,
        },
      }));

      try {
        // Convert image URL to backend API URL
        const apiUrl = convertImageUrlToApiUrl(imageUrl);

        // Use backend API to get the image
        const response = await fetch(apiUrl);

        if (!response.ok) {
          throw new Error(`Failed to load image: ${response.statusText}`);
        }

        // Get image as blob and convert to base64
        const blob = await response.blob();
        const reader = new FileReader();

        reader.onloadend = () => {
          const base64Data = reader.result as string;
          // Remove data URL prefix (e.g., "data:image/png;base64,")
          const base64 = base64Data.split(",")[1] || base64Data;

          setImageData((prev) => ({
            ...prev,
            [imageUrl]: {
              base64Data: base64,
              contentType: blob.type || "image/jpeg",
              isLoading: false,
              loadAttempts: (prev[imageUrl]?.loadAttempts || 0) + 1,
            },
          }));
          loadingImages.current.delete(imageUrl);
        };

        reader.onerror = () => {
          log.error("Failed to read image blob");
          handleImageLoadFail(imageUrl);
          loadingImages.current.delete(imageUrl);
        };

        reader.readAsDataURL(blob);
      } catch (error) {
        log.error(t("chatRightPanel.imageProxyError"), error);
        // If loading fails, remove it directly from the list
        handleImageLoadFail(imageUrl);
        loadingImages.current.delete(imageUrl);
      }

      return Promise.resolve();
    },
    [handleImageLoadFail]
  );

  // Listen for message changes, update search results and images
  useEffect(() => {
    // Process search results
    if (
      currentMessage?.searchResults &&
      Array.isArray(currentMessage.searchResults)
    ) {
      try {
        const results = currentMessage.searchResults.map((result, index) => {
          const processed = {
            title: result.title || t("chatRightPanel.unknownTitle"),
            url: result.url || "#",
            text: result.text || t("chatRightPanel.noContentDescription"),
            published_date: result.published_date || "",
            source_type: result.source_type || "url",
            filename: result.filename || "",
            score: typeof result.score === "number" ? result.score : undefined,
            score_details: result.score_details || {},
            isExpanded: false,
          };

          return processed;
        });

        setSearchResults(results);
      } catch (error) {
        log.error(t("chatRightPanel.processSearchResultsError"), error);
        setSearchResults([]);
      }
    } else {
      setSearchResults([]);
    }

    // Process images from the current message
    if (currentMessage?.images && Array.isArray(currentMessage.images)) {
      // Get unique images from the message
      const allImages = currentMessage.images;

      // Filter out images that have been marked as permanently failed
      const validImages = allImages.filter((imageUrl) => {
        const imgState = imageData[imageUrl];
        // Keep image if: never tried, still loading, or has data (not in error state)
        // Remove image if: has error AND loadAttempts >= 3
        if (imgState?.error && (imgState?.loadAttempts || 0) >= 3) {
          return false;
        }
        return true;
      });

      setProcessedImages(validImages);

      // Preload images - only load if not already loaded and not currently loading
      validImages.forEach((imageUrl) => {
        const imgState = imageData[imageUrl];
        // Load if: no state, or has error but not yet reached max attempts
        const shouldLoad =
          !imgState ||
          (imgState.error &&
            (imgState.loadAttempts || 0) < 3 &&
            !imgState.isLoading);

        if (shouldLoad) {
          loadImage(imageUrl);
        }
      });
    } else {
      setProcessedImages([]);
    }
  }, [
    currentMessage?.searchResults,
    currentMessage?.images,
    selectedMessageId,
    // Include imageData to re-render when image loading state changes
    imageData,
    // Include loadImage and handleImageLoadFail to avoid stale closures
    loadImage,
    handleImageLoadFail,
  ]);

  // Handle image click
  const handleImageClick = (imageUrl: string) => {
    setViewingImage(imageUrl);
  };

  // Render image component
  const renderImage = (imageUrl: string, index: number) => {
    const item = imageData[imageUrl];

    // If the image is loading
    if (!item || item.isLoading) {
      return (
        <div className="flex items-center justify-center w-full h-32 bg-gray-100">
          <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-blue-500"></div>
        </div>
      );
    }

    // If the image loading fails, we should not display it, but since it has been filtered out earlier, this is just for safety
    if (item.error || !item.base64Data) {
      return null;
    }

    // Return base64 image
    return (
      <img
        src={`data:${item.contentType};base64,${item.base64Data}`}
        alt={t("chatRightPanel.imageAlt", { index: index + 1 })}
        className="w-full h-32 object-cover"
        onError={(e) => {
          // Mark the image as failed to load and remove it from the list
          handleImageLoadFail(imageUrl);
        }}
      />
    );
  };

  return (
    <div
      className={`transition-all duration-300 ease-in-out ${
        isVisible ? "lg:flex w-[400px]" : "lg:flex w-0 opacity-0"
      } hidden border-l bg-background relative flex-col h-full bg-white`}
      style={{ maxWidth: "400px", overflow: "hidden" }}
    >
      {/* Image viewer modal */}
      {viewingImage && (
        <div
          className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/80"
          onClick={() => setViewingImage(null)}
        >
          <div className="relative max-w-[90vw] max-h-[90vh]">
            <Button
              type="text"
              size="middle"
              className="absolute top-2 right-2 z-50 rounded-full bg-black/50 text-white hover:bg-black/70 h-8 w-8 p-0"
              onClick={(e: React.MouseEvent) => {
                e.stopPropagation();
                setViewingImage(null);
              }}
            >
              <X className="h-5 w-5" />
            </Button>
            {viewingImage &&
            imageData[viewingImage] &&
            !imageData[viewingImage].isLoading &&
            imageData[viewingImage].base64Data ? (
              <img
                src={`data:${imageData[viewingImage].contentType};base64,${imageData[viewingImage].base64Data}`}
                alt={t("chatRightPanel.viewLargerImageAlt")}
                className="max-w-full max-h-[90vh] object-contain"
                onClick={(e: React.MouseEvent) => e.stopPropagation()}
              />
            ) : (
              <div className="flex items-center justify-center bg-black p-10">
                <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-white"></div>
              </div>
            )}
          </div>
        </div>
      )}

      <div
        className="flex-none sticky top-0 z-20 flex items-center justify-between border-b p-2 bg-gray-50"
        style={{ maxWidth: "400px", overflow: "hidden" }}
      >
        <div className="flex items-center space-x-1">
          <h3 className="text-sm font-semibold text-gray-800 pl-2">
            {t("chatRightPanel.searchTitle")}
          </h3>
        </div>

        {toggleRightPanel && (
          <Button
            type="text"
            size="small"
            className="p-0 h-7 w-7 min-w-[28px] rounded hover:bg-gray-200 active:bg-gray-300 flex items-center justify-center transition-colors duration-200"
            onClick={toggleRightPanel}
            title={t("chatRightPanel.closeSidebarTitle")}
          >
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>

      <div
        className="flex-1 flex flex-col"
        style={{ maxWidth: "400px", height: "100%" }}
      >
        {/* Tab Headers */}
        <div className="flex border-b bg-gray-50">
          <Button
            type={activeTab === "sources" ? "primary" : "text"}
            className={`flex-1 px-3 py-2 text-sm font-medium transition-colors rounded-none border-none ${
              activeTab === "sources"
                ? "bg-white text-gray-900 border-b-2 border-blue-500"
                : "text-gray-500 hover:text-gray-700 hover:bg-gray-100"
            }`}
            onClick={() => setActiveTab("sources")}
          >
            <span className="flex items-center justify-center">
              {t("chatRightPanel.sources")}
              {searchResults.length > 0 && (
                <span className="ml-1 bg-gray-200 inline-flex items-center justify-center rounded px-1 text-xs font-medium min-w-[20px] h-[18px]">
                  {searchResults.length}
                </span>
              )}
            </span>
          </Button>
          <Button
            type={activeTab === "images" ? "primary" : "text"}
            className={`flex-1 px-3 py-2 text-sm font-medium transition-colors rounded-none border-none ${
              activeTab === "images"
                ? "bg-white text-gray-900 border-b-2 border-blue-500"
                : "text-gray-500 hover:text-gray-700 hover:bg-gray-100"
            }`}
            onClick={() => setActiveTab("images")}
          >
            <span className="flex items-center justify-center">
              {t("chatRightPanel.images")}
              {processedImages.length > 0 && (
                <span className="ml-1 bg-gray-200 inline-flex items-center justify-center rounded px-1 text-xs font-medium min-w-[20px] h-[18px]">
                  {processedImages.length}
                </span>
              )}
            </span>
          </Button>
        </div>

        {/* Tab Content */}
        <div className="flex-1 overflow-y-auto">
          {activeTab === "sources" && (
            <div className="p-4" style={{ maxWidth: "400px" }}>
              <div className="space-y-2" style={{ maxWidth: "100%" }}>
                {searchResults.length > 0 ? (
                  <>
                    <div className="space-y-3" style={{ maxWidth: "100%" }}>
                      {searchResults.map((result, index) => (
                        <SearchResultItem
                          key={`result-${index}`}
                          result={result}
                          t={t}
                          appConfig={appConfig}
                        />
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="text-center text-gray-500 py-4 text-base">
                    {t("chatRightPanel.noSearchResults")}
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === "images" && (
            <div className="p-4" style={{ maxWidth: "400px" }}>
              {processedImages.length > 0 ? (
                <>
                  <div className="grid grid-cols-2 gap-2">
                    {processedImages
                      .slice(0, expandedImages ? undefined : maxInitialImages)
                      .map((imageUrl: string, index: number) => (
                        <div
                          key={`img-${index}`}
                          className="relative border rounded-md overflow-hidden hover:border-blue-500 transition-colors cursor-pointer"
                          onClick={() => handleImageClick(imageUrl)}
                        >
                          {renderImage(imageUrl, index)}
                        </div>
                      ))}
                  </div>

                  {processedImages.length > maxInitialImages && (
                    <div className="mt-4 text-center">
                      <Button
                        type="default"
                        size="small"
                        onClick={() => setExpandedImages(!expandedImages)}
                        className="w-full"
                      >
                        {expandedImages
                          ? t("chatRightPanel.collapseImages")
                          : t("chatRightPanel.expandImages", {
                              count: processedImages.length,
                            })}
                      </Button>
                    </div>
                  )}
                </>
              ) : (
                <div className="flex flex-col items-center justify-center p-6 text-center min-h-[200px]">
                  <Database className="h-12 w-12 text-muted-foreground/40 mb-4" />
                  <p className="text-lg font-medium mb-2">
                    {t("chatRightPanel.noImages")}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {t("chatRightPanel.noAssociatedImages")}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
