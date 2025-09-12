import React from "react";
import { useTranslation } from "react-i18next";
import { Copy } from "lucide-react";

import { copyToClipboard } from "@/lib/clipboard";
import log from "@/lib/logger";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";


interface CopyButtonProps {
  content: string;
  variant?: "default" | "code-block" | "message";
  size?: "sm" | "md" | "lg";
  className?: string;
  disabled?: boolean;
  onCopySuccess?: () => void;
  onCopyError?: (error: Error) => void;
  tooltipText?: {
    copy: string;
    copied: string;
  };
}

export const CopyButton: React.FC<CopyButtonProps> = ({
  content,
  variant = "default",
  size = "md",
  className = "",
  disabled = false,
  onCopySuccess,
  onCopyError,
  tooltipText,
}) => {
  const { t } = useTranslation("common");
  const [copied, setCopied] = React.useState(false);

  const handleCopy = async () => {
    if (!content || disabled) return;

    try {
      await copyToClipboard(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      onCopySuccess?.();
    } catch (error) {
      log.error("Failed to copy content:", error);
      onCopyError?.(error as Error);
    }
  };

  // Default tooltip text
  const defaultTooltipText = {
    copy: t("copyButton.copy", "复制"),
    copied: t("copyButton.copied", "已复制"),
  };

  const finalTooltipText = tooltipText || defaultTooltipText;

  // Variant-specific styles
  const getVariantStyles = () => {
    switch (variant) {
      case "code-block":
        return {
          button: `copy-button absolute top-2 right-2 p-1.5 rounded-md transition-colors duration-200 border ${
            copied
              ? "bg-green-50 text-green-600 border-green-200"
              : "bg-gray-100 hover:bg-gray-200 border-gray-200"
          }`,
          icon: "h-4 w-4",
          style: { zIndex: 10 },
        };
      case "message":
        return {
          button: `h-8 w-8 rounded-full bg-white hover:bg-gray-100 transition-all duration-200 shadow-sm ${
            copied ? "bg-green-50 text-green-600 border-green-200" : ""
          }`,
          icon: "h-4 w-4",
          style: {},
        };
      default:
        return {
          button: `transition-all duration-200 ${
            copied ? "bg-green-50 text-green-600 border-green-200" : ""
          }`,
          icon: "h-4 w-4",
          style: {},
        };
    }
  };

  const variantStyles = getVariantStyles();

  // Size-specific styles
  const getSizeStyles = () => {
    switch (size) {
      case "sm":
        return "h-6 w-6";
      case "lg":
        return "h-10 w-10";
      default:
        return "h-8 w-8";
    }
  };

  const sizeStyles = getSizeStyles();

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="outline"
            size="icon"
            className={`${variantStyles.button} ${sizeStyles} ${className}`}
            onClick={handleCopy}
            disabled={disabled || copied}
            style={variantStyles.style}
            title={copied ? finalTooltipText.copied : finalTooltipText.copy}
          >
            <Copy className={variantStyles.icon} />
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>{copied ? finalTooltipText.copied : finalTooltipText.copy}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};
