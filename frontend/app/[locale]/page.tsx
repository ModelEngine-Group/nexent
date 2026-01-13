"use client";

import { useRouter } from "next/navigation";
import { HomepageContent } from "@/components/homepage/HomepageContent";
import { useAuth } from "@/hooks/useAuth";

export default function Home() {
  const router = useRouter();
  const { user, isSpeedMode } = useAuth();

  const handleAuthRequired = () => {
    // This will trigger the global auth dialogs in the layout
    if (!isSpeedMode && !user) {
      // The layout component will handle showing the login prompt
    }
  };

  const handleAdminRequired = () => {
    // This will trigger the global auth dialogs in the layout
    if (!isSpeedMode && user?.role !== "admin") {
      // The layout component will handle showing the admin prompt
    }
  };

  return (
    <div className="w-full h-full flex items-center justify-center p-4">
      <HomepageContent
        onAuthRequired={handleAuthRequired}
        onAdminRequired={handleAdminRequired}
        onChatNavigate={() => router.push('chat')}
        onSetupNavigate={() => router.push('setup')}
        onSpaceNavigate={() => router.push('space')}
      />
    </div>
  );

}
