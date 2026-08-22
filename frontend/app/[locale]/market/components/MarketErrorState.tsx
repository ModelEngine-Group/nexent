"use client";

import React from "react";
import { Empty } from "antd";
import { useTranslation } from "react-i18next";
import { 
  ServerCrash, 
  WifiOff, 
  Clock, 
  AlertTriangle 
} from "lucide-react";

interface MarketErrorStateProps {
  type: "timeout" | "network" | "server" | "unknown";
}

/**
 * Market Error State Component
 * Displays error states for market API failures
 * Style matches MarketContent design
 */
export default function MarketErrorState({ type }: MarketErrorStateProps) {
  const { t } = useTranslation("common");

  const errorConfig = {
    timeout: {
      icon: Clock,
      title: t("market.error.timeout.title", "Request Timeout"),
      description: t(
        "market.error.timeout.description",
        "The market server is taking too long to respond. Please check your network connection and try again."
      ),
    },
    network: {
      icon: WifiOff,
      title: t("market.error.network.title", "Network Error"),
      description: t(
        "market.error.network.description",
        "Unable to connect to the market server. Please check your internet connection."
      ),
    },
    server: {
      icon: ServerCrash,
      title: t("market.error.server.title", "Server Error"),
      description: t(
        "market.error.server.description",
        "The market server encountered an error. Please try again later."
      ),
    },
    unknown: {
      icon: AlertTriangle,
      title: t("market.error.unknown.title", "Something Went Wrong"),
      description: t(
        "market.error.unknown.description",
        "An unexpected error occurred. Please try again."
      ),
    },
  };

  const config = errorConfig[type];
  const Icon = config.icon;

  return (
    <div className="flex items-center justify-center py-16">
      <div className="text-center max-w-2xl">
        {/* Icon and Title Row */}
        <div className="flex items-center justify-center gap-3 mb-4">
          <div className="w-12 h-12 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
            <Icon className="h-6 w-6 text-slate-400 dark:text-slate-500" />
          </div>
          <div className="text-lg font-medium text-slate-700 dark:text-slate-300">
            {config.title}
          </div>
        </div>
        
        {/* Description */}
        <div className="text-sm text-slate-500 dark:text-slate-400 px-8">
          {config.description}
        </div>
      </div>
    </div>
  );
}

