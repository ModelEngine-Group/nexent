"use client";

import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  Bot,
  Globe,
  Zap,
  MessagesSquare,
  Unplug,
  TextQuote,
  AlertTriangle,
} from "lucide-react";
import { Button } from "antd";
import { Card, CardContent } from "@/components/ui/card";
import { motion } from "framer-motion";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";

/**
 * Homepage main content component
 */
export default function Homepage() {
  const { t } = useTranslation("common");
  const { isSpeedMode } = useDeployment();
  const { isAuthenticated, openAuthPromptModal } = useAuthenticationContext();
  const { canAccessRoute, openAuthzPromptModal } = useAuthorizationContext();
  const router = useRouter();

  /**
 * Navigate to a route with permission pre-check
 * Returns true if navigation is allowed, false if permission is denied
 */
  const navigateWithPermissionCheck = (route: string): boolean => {
    // Check authentication first
    if (!isAuthenticated && !isSpeedMode) {
      openAuthPromptModal();
      return false;
    }

    // Check authorization - if user is authenticated but doesn't have route access
    if (isAuthenticated && !canAccessRoute(route)) {
      openAuthzPromptModal();
      return false;
    }

    // User has permission, navigate
    router.push(route);
    return true;
  };

  const navigateToChat = () => navigateWithPermissionCheck("/chat");
  const navigateToSetup = () => navigateWithPermissionCheck("/setup");
  const navigateToSpace = () => navigateWithPermissionCheck("/space");

  return (
    <div className="w-full h-full flex flex-col items-center justify-center">
      {/* Hero area */}
      <section className="relative w-full py-4 flex flex-col items-center justify-center text-center">
        <div className="absolute inset-0 bg-grid-slate-200 dark:bg-grid-slate-800 [mask-image:radial-gradient(ellipse_at_center,white_20%,transparent_75%)] -z-10"></div>
        <motion.h2
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
          className="text-4xl md:text-5xl lg:text-6xl font-bold text-slate-900 dark:text-white mb-4 tracking-tight"
        >
          {t("page.title")}
          <span className="text-blue-600 dark:text-blue-500">
            {" "}
            {t("page.subtitle")}
          </span>
        </motion.h2>
        <motion.p
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.3 }}
          className="max-w-2xl text-slate-600 dark:text-slate-300 text-lg md:text-xl mb-8"
        >
          {t("page.description")}
        </motion.p>

        {/* Three parallel buttons */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.4 }}
          className="flex flex-col sm:flex-row gap-4"
        >
          
          <Button
            onClick={navigateToChat}
            className="bg-blue-600 hover:bg-blue-700 text-white px-8 py-6 rounded-full text-lg font-medium shadow-lg hover:shadow-xl transition-all duration-300 group"
          >
            <Bot className="mr-2 h-5 w-5 group-hover:animate-pulse" />
            {t("page.startChat")}
          </Button>

          <Button
            onClick={navigateToSetup}
            className="bg-blue-600 hover:bg-blue-700 text-white px-8 py-6 rounded-full text-lg font-medium shadow-lg hover:shadow-xl transition-all duration-300 group"
          >
            <Zap className="mr-2 h-5 w-5 group-hover:animate-pulse" />
            {t("page.quickConfig")}
          </Button>

          <Button
            onClick={navigateToSpace}
            className="bg-blue-600 hover:bg-blue-700 text-white px-8 py-6 rounded-full text-lg font-medium shadow-lg hover:shadow-xl transition-all duration-300 group"
          >
            <Globe className="mr-2 h-5 w-5 group-hover:animate-pulse" />
            {t("page.agentSpace")}
          </Button>
        </motion.div>

        {/* Data protection notice - only shown in full version */}
        {!isSpeedMode && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.5 }}
            className="mt-12 flex items-center justify-center gap-2 text-sm text-slate-500 dark:text-slate-400"
          >
            <AlertTriangle className="h-4 w-4" />
            <span>{t("page.dataProtection")}</span>
          </motion.div>
        )}
      </section>

      {/* Feature cards */}
      <motion.section
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, delay: 0.6 }}
        className="w-full mt-1 max-w-7xl"
      >
        <motion.h3
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.7 }}
          className="text-2xl font-bold text-slate-900 dark:text-white mb-6 text-center"
        >
          {t("page.coreFeatures")}
        </motion.h3>
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.8 }}
          className="grid grid-cols-1 md:grid-cols-2 gap-4 "
        >

          {(
            t("page.features", { returnObjects: true }) as Array<{
              title: string;
              description: string;
            }>
          ).map((feature, index: number) => {
            const icons = [
              <Bot key={0} className="h-8 w-8 text-blue-500" />,
              <TextQuote key={1} className="h-8 w-8 text-green-500" />,
              <Zap key={2} className="h-8 w-8 text-blue-500" />,
              <Globe key={3} className="h-8 w-8 text-emerald-500" />,
              <Unplug key={4} className="h-8 w-8 text-amber-500" />,
              <MessagesSquare key={5} className="h-8 w-8 text-purple-500" />,
            ];

            return (
              <motion.div
                key={index}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{
                  duration: 0.6,
                  delay: 0.9 + index * 0.1,
                }}
              >
                <FeatureCard
                  icon={
                    icons[index] || <Bot className="h-8 w-8 text-blue-500" />
                  }
                  title={feature.title}
                  description={feature.description}
                />
              </motion.div>
            );
          })}


        </motion.div>
      </motion.section>
    </div>
  );
}

// Feature card component
interface FeatureCardProps {
  icon: React.ReactNode;
  title: string;
  description: string;
}

function FeatureCard({ icon, title, description }: FeatureCardProps) {
  return (
    <Card className="overflow-hidden border border-slate-200 dark:border-slate-700 transition-all duration-300 hover:shadow-md hover:border-blue-200 dark:hover:border-blue-900/30 group h-32">
      <CardContent className="p-5 flex flex-row items-center gap-4 h-full">
        <div className="flex-shrink-0 p-3 bg-slate-100 dark:bg-slate-800 rounded-full group-hover:bg-blue-100 dark:group-hover:bg-blue-900/30 transition-colors">
          {icon}
        </div>
        <div className="flex-1 min-w-0 flex flex-col justify-center">
          <h4 className="text-lg font-semibold text-slate-900 dark:text-white mb-2">
            {title}
          </h4>
          <p className="text-sm text-slate-600 dark:text-slate-300 line-clamp-3">
            {description}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}