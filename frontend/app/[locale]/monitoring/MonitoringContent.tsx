"use client";

import React from "react";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Activity } from "lucide-react";

import { useSetupFlow } from "@/hooks/useSetupFlow";
import { ConnectionStatus } from "@/const/modelConfig";

interface MonitoringContentProps {
  /** Connection status */
  connectionStatus?: ConnectionStatus;
  /** Is checking connection */
  isCheckingConnection?: boolean;
  /** Check connection callback */
  onCheckConnection?: () => void;
  /** Callback to expose connection status */
  onConnectionStatusChange?: (status: ConnectionStatus) => void;
}

/**
 * MonitoringContent - Agent monitoring and operations coming soon page
 * This will allow admins to monitor and operate agents (health, logs, alerts)
 */
export default function MonitoringContent({
  connectionStatus: externalConnectionStatus,
  isCheckingConnection: externalIsCheckingConnection,
  onCheckConnection: externalOnCheckConnection,
  onConnectionStatusChange,
}: MonitoringContentProps) {
  const { t } = useTranslation("common");

  // Use custom hook for common setup flow logic
  const { canAccessProtectedData, pageVariants, pageTransition } = useSetupFlow({
    requireAdmin: true,
    externalConnectionStatus,
    externalIsCheckingConnection,
    onCheckConnection: externalOnCheckConnection,
    onConnectionStatusChange,
  });

  return (
    <>
      {canAccessProtectedData ? (
        <motion.div
          initial="initial"
          animate="in"
          exit="out"
          variants={pageVariants}
          transition={pageTransition}
          className="w-full h-full flex items-center justify-center"
        >
          <div className="flex flex-col items-center justify-center space-y-6 p-8 max-w-md text-center">
            {/* Icon */}
            <motion.div
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ delay: 0.2, type: "spring", stiffness: 200 }}
              className="w-24 h-24 rounded-full bg-gradient-to-br from-emerald-500 to-sky-600 flex items-center justify-center shadow-lg"
            >
              <Activity className="h-12 w-12 text-white" />
            </motion.div>

            {/* Title */}
            <motion.h1
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
              className="text-3xl font-bold text-slate-800 dark:text-slate-100"
            >
              {t("monitoring.comingSoon.title")}
            </motion.h1>

            {/* Description */}
            <motion.p
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 }}
              className="text-lg text-slate-600 dark:text-slate-400"
            >
              {t("monitoring.comingSoon.description")}
            </motion.p>

            {/* Feature list */}
            <motion.ul
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.5 }}
              className="text-left space-y-2 w-full"
            >
              <li className="flex items-start space-x-2">
                <span className="text-emerald-500 mt-1">✓</span>
                <span className="text-slate-600 dark:text-slate-400">
                  {t("monitoring.comingSoon.feature1")}
                </span>
              </li>
              <li className="flex items-start space-x-2">
                <span className="text-emerald-500 mt-1">✓</span>
                <span className="text-slate-600 dark:text-slate-400">
                  {t("monitoring.comingSoon.feature2")}
                </span>
              </li>
              <li className="flex items-start space-x-2">
                <span className="text-emerald-500 mt-1">✓</span>
                <span className="text-slate-600 dark:text-slate-400">
                  {t("monitoring.comingSoon.feature3")}
                </span>
              </li>
            </motion.ul>

            {/* Coming soon badge */}
            <motion.div
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.6 }}
              className="px-4 py-2 bg-gradient-to-r from-emerald-500 to-sky-600 text-white rounded-full text-sm font-medium shadow-md"
            >
              {t("monitoring.comingSoon.badge")}
            </motion.div>
          </div>
        </motion.div>
      ) : null}
    </>
  );
}


