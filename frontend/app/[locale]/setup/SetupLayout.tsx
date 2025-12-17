"use client";

import {ReactNode} from "react";
import {useTranslation} from "react-i18next";

// ================ Navigation ================
interface NavigationProps {
  onBack?: () => void;
  onNext?: () => void;
  onComplete?: () => void;
  isSaving?: boolean;
  showBack?: boolean;
  showNext?: boolean;
  showComplete?: boolean;
  nextText?: string;
  completeText?: string;
}

function Navigation({
  onBack,
  onNext,
  onComplete,
  isSaving = false,
  showBack = false,
  showNext = false,
  showComplete = false,
  nextText,
  completeText,
}: NavigationProps) {
  const { t } = useTranslation();

  const handleClick = () => {
    if (showComplete && onComplete) {
      onComplete();
    } else if (showNext && onNext) {
      onNext();
    }
  };

  const buttonText = () => {
    if (showComplete) {
      return isSaving
        ? t("setup.navigation.button.saving")
        : completeText || t("setup.navigation.button.complete");
    }
    if (showNext) {
      return nextText || t("setup.navigation.button.next");
    }
    return "";
  };

  return (
    <div className="mt-3 flex justify-between" style={{ padding: "0 16px" }}> 
      <div className="flex gap-2">
        {showBack && onBack && (
          <button
            onClick={onBack}
            className="px-6 py-2.5 rounded-md flex items-center text-sm font-medium bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 cursor-pointer transition-colors"
          >
            {t("setup.navigation.button.previous")}
          </button>
        )}
      </div>

      <div className="flex gap-2">
        {(showNext || showComplete) && (
          <button
            onClick={handleClick}
            disabled={isSaving}
            className="px-6 py-2.5 rounded-md flex items-center text-sm font-medium bg-blue-600 dark:bg-blue-600 text-white hover:bg-blue-700 dark:hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            style={{
              border: "none",
              marginLeft: !showBack ? "auto" : undefined,
            }}
          >
            {buttonText()}
          </button>
        )}
      </div>
    </div>
  );
}

// ================ Layout ================
interface SetupLayoutProps {
  children: ReactNode;
  onBack?: () => void;
  onNext?: () => void;
  onComplete?: () => void;
  isSaving?: boolean;
  showBack?: boolean;
  showNext?: boolean;
  showComplete?: boolean;
  nextText?: string;
  completeText?: string;
}

/**
 * SetupLayout - Content wrapper for setup pages
 * This component should be wrapped by NavigationLayout
 */
export default function SetupLayout({
  children,
  onBack,
  onNext,
  onComplete,
  isSaving = false,
  showBack = false,
  showNext = false,
  showComplete = false,
  nextText,
  completeText,
}: SetupLayoutProps) {
  return (
    <div className="w-full h-full bg-slate-50 dark:bg-slate-900 font-sans overflow-hidden">
      {/* Main content with fixed size */}
      <div className="max-w-[1800px] mx-auto px-8 pb-6 pt-6 bg-transparent h-full flex flex-col">
        <div className="flex-1 w-full h-full flex items-center justify-center">
        {children}
        </div>
        <Navigation
          onBack={onBack}
          onNext={onNext}
          onComplete={onComplete}
          isSaving={isSaving}
          showBack={showBack}
          showNext={showNext}
          showComplete={showComplete}
          nextText={nextText}
          completeText={completeText}
        />
      </div>
    </div>
  );
}
