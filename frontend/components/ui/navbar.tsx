"use client";

import { Button } from "@/components/ui/button";
import { AvatarDropdown } from "@/components/auth/avatarDropdown";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/hooks/useAuth";
import { ChevronDown, Globe } from "lucide-react";
import { Dropdown } from "antd";
import Link from "next/link";
import { HEADER_CONFIG } from "@/const/layoutConstants";
import { languageOptions } from "@/const/constants";
import { useLanguageSwitch } from "@/lib/language";

/**
 * Main navigation bar component
 * Displays logo, navigation links, language switcher, and user authentication status
 */
export function Navbar() {
  const { t } = useTranslation("common");
  const { user, isLoading: userLoading, isSpeedMode } = useAuth();
  const { currentLanguage, handleLanguageChange } = useLanguageSwitch();

  return (
    <header
      className="w-full py-4 px-6 flex items-center justify-between border-b border-slate-200 dark:border-slate-700 bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm fixed top-0 z-10"
      style={{ height: HEADER_CONFIG.DISPLAY_HEIGHT }}
    >
      {/* Left section - Logo */}
      <Link href="/" className="flex items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity">
        <h1 className="text-xl font-bold text-slate-900 dark:text-white flex items-start">
          <img
            src="/modelengine-logo2.png"
            alt="ModelEngine"
            className="h-6"
          />
          <span className="text-blue-600 dark:text-blue-500 ml-2">
            {t("assistant.name")}
          </span>
        </h1>
      </Link>

      {/* Right section - Navigation links and user controls */}
      <div className="hidden md:flex items-center gap-6">
        {/* GitHub link */}
        <Link
          href="https://github.com/ModelEngine-Group/nexent"
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white transition-colors flex items-center gap-1"
        >
          <svg
            height="18"
            width="18"
            viewBox="0 0 16 16"
            fill="currentColor"
            aria-hidden="true"
          >
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.65 7.65 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.19 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"></path>
          </svg>
          Github
        </Link>

        {/* ModelEngine link */}
        <Link
          href="http://modelengine-ai.net"
          className="text-sm font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white transition-colors"
        >
          ModelEngine
        </Link>

        {/* Language switcher */}
        <Dropdown
          menu={{
            items: languageOptions.map((opt) => ({
              key: opt.value,
              label: opt.label,
            })),
            onClick: ({ key }) => handleLanguageChange(key as string),
          }}
        >
          <a className="ant-dropdown-link text-sm font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white transition-colors flex items-center gap-2 cursor-pointer w-[100px] border-0 shadow-none bg-transparent text-left">
            <Globe className="h-4 w-4" />
            {languageOptions.find((o) => o.value === currentLanguage)?.label ||
              currentLanguage}
            <ChevronDown size={12} />
          </a>
        </Dropdown>

        {/* User status - only shown in full version */}
        {!isSpeedMode && (
          <>
            {userLoading ? (
              <span className="text-sm font-medium text-slate-600">
                {t("common.loading")}...
              </span>
            ) : user ? (
              <span className="text-sm font-medium text-slate-600">
                {user.email}
              </span>
            ) : null}
            <AvatarDropdown />
          </>
        )}
      </div>

      {/* Mobile hamburger menu button */}
      <Button variant="ghost" size="icon" className="md:hidden">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="h-6 w-6"
        >
          <line x1="4" x2="20" y1="12" y2="12" />
          <line x1="4" x2="20" y1="6" y2="6" />
          <line x1="4" x2="20" y1="18" y2="18" />
        </svg>
      </Button>
    </header>
  );
}

