"use client";

import {
  useEffect,
  useRef,
  useState,
  type ComponentProps,
  type MouseEvent,
} from "react";
import { createPortal } from "react-dom";
import { ImageIcon, XIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchImageBlob } from "@/services/storageService";

/**
 * Detect whether a given URL points to an AIDP KnowledgeBase image that
 * requires a Bearer token to access. AIDP image URLs always include
 * `/KnowledgeBase/Tenants/` in their path and use the http(s) scheme.
 *
 * Non-AIDP URLs (e.g. MinIO /api/file/*, external CDNs, duckduckgo favicons)
 * do NOT require backend authentication and will be rendered as plain <img src>.
 */
const isAidpImageUrl = (url: string): boolean => {
  return (
    typeof url === "string" &&
    (url.startsWith("http://") || url.startsWith("https://")) &&
    url.includes("/KnowledgeBase/Tenants/")
  );
};

/**
 * Image component that automatically fetches AIDP-hosted images through the
 * backend proxy (which adds the Bearer token the AIDP API requires).
 *
 * - AIDP URLs  -> fetched via `fetchImageBlob` -> base64 data URL rendered in <img>.
 * - Other URLs -> rendered directly as plain <img src={url}>.
 *
 * This component is a drop-in replacement for <img>, accepts the same props,
 * and transparently handles the authentication for any image that needs it
 * without affecting the rendering of non-authenticated images.
 */
export const AuthenticatedImage: React.FC<
  ComponentProps<"img"> & {
    /** Custom placeholder rendered while loading or on error. */
    fallback?: React.ReactNode;
    /** Open the already-resolved image in an in-page lightbox on click. */
    preview?: boolean;
  }
> = ({ src, alt, className, fallback, preview = false, ...imgProps }) => {
  const needsAuth = src ? isAidpImageUrl(src) : false;

  // Non-AIDP image: render directly, no fetch required.
  if (!needsAuth) {
    return (
      <PlainPreviewableImage
        src={src}
        alt={alt}
        className={className}
        preview={preview}
        {...imgProps}
      />
    );
  }

  // AIDP image: go through the authed proxy path.
  return (
    <AuthedAidpImage
      src={src!}
      alt={alt}
      className={className}
      fallback={fallback}
      preview={preview}
      {...imgProps}
    />
  );
};

const PlainPreviewableImage: React.FC<
  ComponentProps<"img"> & { preview: boolean }
> = ({ src, alt, className, preview, onClick, ...imgProps }) => {
  const [previewOpen, setPreviewOpen] = useState(false);

  const handleClick = (event: MouseEvent<HTMLImageElement>) => {
    onClick?.(event);
    if (preview && !event.defaultPrevented) setPreviewOpen(true);
  };

  return (
    <>
      <img
        src={src}
        alt={alt}
        className={cn(preview && "cursor-zoom-in", className)}
        onClick={handleClick}
        {...imgProps}
      />
      {previewOpen && src ? (
        <ImagePreviewOverlay
          src={src}
          alt={alt}
          onClose={() => setPreviewOpen(false)}
        />
      ) : null}
    </>
  );
};

const AuthedAidpImage: React.FC<
  ComponentProps<"img"> & {
    src: string;
    fallback?: React.ReactNode;
    preview?: boolean;
  }
> = ({
  src,
  alt,
  className,
  fallback,
  preview = false,
  onClick,
  ...imgProps
}) => {
  const [dataUrl, setDataUrl] = useState<string | null>(null);
  const [errored, setErrored] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const readerRef = useRef<FileReader | null>(null);

  useEffect(() => {
    if (!src) return;
    setErrored(false);
    setDataUrl(null);

    let cancelled = false;
    const reader = new FileReader();
    readerRef.current = reader;

    reader.onloadend = () => {
      if (cancelled) return;
      setDataUrl(reader.result as string);
    };
    reader.onerror = () => {
      if (cancelled) return;
      setErrored(true);
    };

    fetchImageBlob(src)
      .then((blob) => {
        if (cancelled) return;
        // Image service proxy might return JSON error body with HTTP 200;
        // `fetchImageBlob` already throws in that case, so reaching here
        // means we have real image bytes.
        reader.readAsDataURL(blob);
      })
      .catch(() => {
        if (cancelled) return;
        setErrored(true);
      });

    return () => {
      cancelled = true;
      reader.abort();
    };
  }, [src]);

  // Loading / error states
  if (errored || !dataUrl) {
    if (errored) {
      if (fallback !== undefined) return <>{fallback}</>;
      return (
        <span
          className={cn(
            "flex items-center justify-center bg-muted/50 text-muted-foreground",
            className
          )}
          aria-label={typeof alt === "string" ? alt : undefined}
        >
          <ImageIcon className="size-6" />
        </span>
      );
    }
    // Loading state: use the loading spinner style from chatRightPanel
    return (
      <span
        className={cn(
          "flex items-center justify-center bg-muted/50",
          className
        )}
        aria-label={typeof alt === "string" ? alt : undefined}
      >
        <span className="animate-spin rounded-full border-2 border-muted-foreground/30 border-t-muted-foreground size-5" />
      </span>
    );
  }

  const handleClick = (event: MouseEvent<HTMLImageElement>) => {
    onClick?.(event);
    if (preview && !event.defaultPrevented) setPreviewOpen(true);
  };

  return (
    <>
      <img
        src={dataUrl}
        alt={alt}
        className={cn(preview && "cursor-zoom-in", className)}
        onClick={handleClick}
        {...imgProps}
      />
      {previewOpen ? (
        <ImagePreviewOverlay
          src={dataUrl}
          alt={alt}
          onClose={() => setPreviewOpen(false)}
        />
      ) : null}
    </>
  );
};

const ImagePreviewOverlay: React.FC<{
  src: string;
  alt?: string;
  onClose: () => void;
}> = ({ src, alt, onClose }) => {
  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={alt || "Image preview"}
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/80 p-4"
      onClick={onClose}
    >
      <button
        type="button"
        aria-label="Close image preview"
        className="absolute top-4 right-4 rounded-full bg-black/60 p-2 text-white transition-colors hover:bg-black/80"
        onClick={onClose}
      >
        <XIcon className="size-5" />
      </button>
      <img
        src={src}
        alt={alt}
        className="max-h-[90vh] max-w-[90vw] object-contain"
        onClick={(event) => event.stopPropagation()}
      />
    </div>,
    document.body
  );
};

export default AuthenticatedImage;
