"use client";

import { useConfig } from "@/hooks/useConfig";
import { extractColorsFromUri } from "@/lib/avatar";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

/**
 * ChatTopNavContent - Displays app logo and name in the top navbar for chat page
 */
export function ChatTopNavContent() {
  const router = useRouter();
  const { i18n } = useTranslation();
  const { appConfig, getAppAvatarUrl } = useConfig();
  const sidebarAvatarUrl = getAppAvatarUrl(16);
  
  // Static font-size for top navbar (no responsive sizing required)

  const colors = extractColorsFromUri(appConfig.avatarUri || "");
  const mainColor = colors.mainColor || "273746";
  const secondaryColor = colors.secondaryColor || mainColor;

  return (
    <div
      className="flex items-center cursor-pointer hover:opacity-80 transition-opacity"
      onClick={() => router.push(`/${i18n.language}`)}
    >
      <div className="h-6 w-6 rounded-full overflow-hidden mr-2">
        <img
          src={sidebarAvatarUrl}
          alt={appConfig.appName}
          className="h-full w-full object-cover"
        />
      </div>
      <span
        className="font-bold truncate bg-clip-text text-transparent"
        style={{
          fontSize: '16px',
          lineHeight: '20px',
          backgroundImage: `linear-gradient(180deg, #${mainColor} 0%, #${secondaryColor} 100%)`,
        }}
      >
        {appConfig.appName}
      </span>
    </div>
  );
}

