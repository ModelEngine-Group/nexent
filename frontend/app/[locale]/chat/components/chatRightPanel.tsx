import { useState, useEffect, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { ExternalLink, Database, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StaticScrollArea } from "@/components/ui/scrollArea";
import { ChatMessageType, ImageItem, ChatRightPanelProps, SearchResult } from "@/types/chat";
import { API_ENDPOINTS } from "@/services/api";
import { formatDate, formatUrl } from "@/lib/utils";
import log from "@/lib/logger";


export function ChatRightPanel({
  messages,
  onImageError,
  maxInitialImages = 4,
  isVisible = false,
  toggleRightPanel,
  selectedMessageId,
}: ChatRightPanelProps) {
  const { t } = useTranslation("common");
  // Local state
  const [expandedImages, setExpandedImages] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [processedImages, setProcessedImages] = useState<string[]>([]);
  const [viewingImage, setViewingImage] = useState<string | null>(null);
  const [imageData, setImageData] = useState<Record<string, ImageItem>>({});

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

  // Load image
  const loadImage = async (imageUrl: string) => {
    // If it is already in the cache and is not loading, return directly
    if (imageData[imageUrl] && !imageData[imageUrl].isLoading) {
      return Promise.resolve();
    }

    // If it is loading, prevent duplicate requests
    if (loadingImages.current.has(imageUrl)) {
      return Promise.resolve();
    }

    // Mark as loading
    loadingImages.current.add(imageUrl);

    // Get the current load attempts
    const currentAttempts = imageData[imageUrl]?.loadAttempts || 0;

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
      // Use the proxy service to get the image
      const response = await fetch(API_ENDPOINTS.proxy.image(imageUrl));
      const data = await response.json();

      if (data.success) {
        setImageData((prev) => ({
          ...prev,
          [imageUrl]: {
            base64Data: data.base64,
            contentType: data.content_type || "image/jpeg",
            isLoading: false,
            loadAttempts: currentAttempts + 1,
          },
        }));
      } else {
        // If loading fails, remove it directly from the list
        handleImageLoadFail(imageUrl);
      }
    } catch (error) {
      log.error(t("chatRightPanel.imageProxyError"), error);
      // If loading fails, remove it directly from the list
      handleImageLoadFail(imageUrl);
    } finally {
      // Whether successful or not, remove the loading mark
      loadingImages.current.delete(imageUrl);
    }

    return Promise.resolve();
  };

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

    // Process images
    if (currentMessage?.images && Array.isArray(currentMessage.images)) {
      // Get and remove duplicates
      const allImages = currentMessage.images;

      // Filter out images that have been marked as failed to load
      const validImages = allImages.filter((imageUrl) => {
        return !(imageData[imageUrl] && imageData[imageUrl].error);
      });

      setProcessedImages(validImages);

      // Preload images, but only load images that are not loaded yet
      const loadPromises = validImages.map((imageUrl) => {
        if (
          !imageData[imageUrl] ||
          (imageData[imageUrl].error === undefined &&
            !imageData[imageUrl].isLoading)
        ) {
          return loadImage(imageUrl);
        }
        return Promise.resolve();
      });

      // Load all images in parallel
      Promise.all(loadPromises).catch((error) => {
        log.error(t("chatRightPanel.parallelLoadImagesError"), error);
      });
    } else {
      setProcessedImages([]);
    }
  }, [
    currentMessage?.searchResults,
    currentMessage?.images,
    selectedMessageId,
  ]);

  // Handle image click
  const handleImageClick = (imageUrl: string) => {
    setViewingImage(imageUrl);
  };

  // Search result item component
  const SearchResultItem = ({ result }: { result: SearchResult }) => {
    const [isExpanded, setIsExpanded] = useState(false);
    const title = result.title || t("chatRightPanel.unknownTitle");
    const url = result.url || "#";
    const text = result.text || t("chatRightPanel.noContentDescription");
    const published_date = result.published_date || "";
    const source_type = result.source_type || "url";

    return (
      <div className="p-3 rounded-lg border border-gray-200 text-xs hover:bg-gray-50 transition-colors overflow-hidden">
        <div className="flex flex-col">
          <div>
            {source_type === "url" ? (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-blue-600 hover:underline block text-base"
                style={{
                  display: "-webkit-box",
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: "vertical",
                  overflow: "hidden",
                  wordBreak: "break-word",
                }}
                title={title}
              >
                {title}
              </a>
            ) : (
              <div
                className="font-medium text-base"
                style={{
                  display: "-webkit-box",
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: "vertical",
                  overflow: "hidden",
                  wordBreak: "break-word",
                }}
                title={title}
              >
                {title}
              </div>
            )}

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
              className="flex items-center overflow-hidden"
              style={{ flex: 1, minWidth: 0 }}
            >
              <div className="w-3 h-3 flex-shrink-0 mr-1">
                {source_type === "url" ? (
                  <ExternalLink className="w-full h-full" />
                ) : source_type === "file" ? (
                  <Database className="w-full h-full" />
                ) : null}
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
        isVisible ? "lg:block w-[400px]" : "lg:block w-0 opacity-0"
      } hidden border-l bg-background relative`}
      style={{ maxWidth: "400px", overflow: "hidden" }}
    >
      {/* Image viewer modal */}
      {viewingImage && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
          onClick={() => setViewingImage(null)}
        >
          <div className="relative max-w-[90vw] max-h-[90vh]">
            <Button
              variant="ghost"
              size="icon"
              className="absolute top-2 right-2 z-50 rounded-full bg-black/50 text-white hover:bg-black/70"
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
            variant="ghost"
            size="sm"
            className="p-1 h-7 w-7 rounded hover:bg-gray-200"
            onClick={toggleRightPanel}
            title={t("chatRightPanel.closeSidebarTitle")}
          >
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>

      <Tabs
        defaultValue="sources"
        style={{ maxWidth: "400px", overflow: "hidden" }}
      >
        <TabsList className="w-full" style={{ maxWidth: "400px" }}>
          <TabsTrigger value="sources" className="flex-1">
            {t("chatRightPanel.sources")}
            {searchResults.length > 0 && (
              <span className="ml-1 bg-gray-200 inline-flex items-center justify-center rounded px-1 text-xs font-medium min-w-[20px] h-[18px]">
                {searchResults.length}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="images" className="flex-1">
            {t("chatRightPanel.images")}
            {processedImages.length > 0 && (
              <span className="ml-1 bg-gray-200 inline-flex items-center justify-center rounded px-1 text-xs font-medium min-w-[20px] h-[18px]">
                {processedImages.length}
              </span>
            )}
          </TabsTrigger>
        </TabsList>

        <StaticScrollArea
          className="h-[calc(100vh-120px)]"
          style={{ maxWidth: "400px", overflow: "hidden" }}
        >
          <TabsContent
            value="sources"
            className="p-4"
            style={{ maxWidth: "400px", overflow: "hidden" }}
          >
            <div
              className="space-y-2"
              style={{ maxWidth: "100%", overflow: "hidden" }}
            >
              {searchResults.length > 0 ? (
                <>
                  <div
                    className="space-y-3"
                    style={{ maxWidth: "100%", overflow: "hidden" }}
                  >
                    {searchResults.map((result, index) => (
                      <SearchResultItem
                        key={`result-${index}`}
                        result={result}
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
          </TabsContent>

          <TabsContent
            value="images"
            className="p-4"
            style={{ maxWidth: "400px", overflow: "hidden" }}
          >
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
                      variant="outline"
                      size="sm"
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
          </TabsContent>
        </StaticScrollArea>
      </Tabs>
    </div>
  );
}
