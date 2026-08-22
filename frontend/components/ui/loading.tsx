import { useTranslation } from "react-i18next";

interface LoadingProps {
  message?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}

export function Loading({
  message,
  size = "md",
  className = "",
}: LoadingProps) {
  const { t } = useTranslation();

  const sizeClasses = {
    sm: "h-8 w-8",
    md: "h-12 w-12",
    lg: "h-16 w-16",
  };

  const defaultMessage = t("common.loading");

  return (
    <div className={`flex items-center justify-center ${className}`}>
      <div className="text-center">
        <div
          className={`animate-spin rounded-full border-b-2 border-primary mx-auto mb-4 ${sizeClasses[size]}`}
        ></div>
        <p className="text-muted-foreground">{message || defaultMessage}</p>
      </div>
    </div>
  );
}

export function FullScreenLoading({
  message,
  size = "md",
}: Omit<LoadingProps, "className">) {
  return (
    <div className="flex h-screen items-center justify-center">
      <Loading message={message} size={size} />
    </div>
  );
}
