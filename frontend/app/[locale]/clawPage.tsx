"use client";

import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  Bot,
  Globe,
  Zap,
  Unplug,
  AlertTriangle,
  ArrowRight,
  Box,
  Server,
  Activity,
} from "lucide-react";
import { Button, Row, Col, Card } from "antd";
import { motion } from "framer-motion";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";

/**
 * Homepage main content component for Meclaw deployment
 */
export default function ClawHomepage() {
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

  const navigateToMeChat = () => navigateWithPermissionCheck("/mechat");
  const navigateToMEMonitor = () => navigateWithPermissionCheck("/memonitor");

  return (
    <div className="w-full min-h-full flex flex-col items-center justify-center pt-6 pb-8">
      {/* Hero area */}
      <section className="relative w-full p-8 pb-12 flex flex-col items-center justify-center text-center flex-shrink-0">
        <div className="absolute inset-0 bg-grid-slate-200 dark:bg-grid-slate-800 [mask-image:radial-gradient(ellipse_at_center,white_20%,transparent_75%)] -z-10"></div>
        <motion.h2
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
          className="text-4xl md:text-5xl lg:text-6xl font-bold text-slate-900 dark:text-white mb-4 tracking-tight"
        >
          {t("page.clawTitle")}
          <span className="text-blue-600 dark:text-blue-500">
            {t("page.clawSubtitle")}
          </span>
        </motion.h2>
        <motion.p
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.3 }}
          className="max-w-2xl text-slate-600 dark:text-slate-300 text-lg md:text-xl mb-8 mt-4"
        >
          {t("page.clawDescription")}
        </motion.p>

        {/* Three parallel buttons - responsive: row on wide, column on narrow */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.4 }}
        >
          <Row gutter={[16, 16]} justify="center">
            <Col xs={24} sm={24} md={10}>
              <Button
                onClick={navigateToMeChat}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white px-8 py-6 text-lg font-medium shadow-lg hover:shadow-xl transition-all duration-300 group"
              >
                {t("page.startClawChat")}
                <ArrowRight className="h-6 w-6 shrink-0 group-hover:translate-x-1 transition-transform" />
              </Button>
            </Col>
            <Col xs={24} sm={24} md={10}>
              <Button
                onClick={navigateToMEMonitor}
                variant="outlined"
                className="w-full border-slate-300 hover:border-slate-400 text-slate-700 dark:text-slate-200 bg-white hover:bg-slate-50 dark:bg-slate-800 dark:hover:bg-slate-700 px-8 py-6 text-lg font-medium shadow-sm hover:shadow-md transition-all duration-300 group"
              >
                {t("page.viewMonitoring")}
                <Activity className="mr-2 h-6 w-6 shrink-0 group-hover:translate-x-1 group-hover:animate-pulse transition-transform" />
              </Button>
            </Col>
          </Row>
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

      {/* Supported scenarios: container and VM - with light gray background */}
      <section className="w-full bg-slate-50 dark:bg-slate-900/50 pt-8 pb-10">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.5 }}
          className="w-full max-w-4xl mx-auto px-8"
        >
          <motion.h3
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.6 }}
            className="text-xl font-bold text-slate-900 dark:text-white mb-6 text-center"
          >
            {t("page.supportedScenarios")}
          </motion.h3>
          <Row gutter={[24, 24]} justify="center">
            <Col xs={24} sm={12} md={12}>
              <Card
                hoverable
                className="h-full bg-white dark:bg-slate-800 border-0 shadow-sm hover:shadow-md transition-all duration-300 rounded-xl"
                styles={{ body: { padding: '20px' } }}
              >
                <div className="flex flex-col items-center text-center">
                  <div className="flex items-center justify-center w-14 h-14 bg-gradient-to-br from-blue-500 to-blue-600 rounded-xl mb-4">
                    <Box className="h-7 w-7 text-white" />
                  </div>
                  <span className="text-lg font-semibold text-slate-900 dark:text-white mb-2">
                    {t("page.scenarioContainer")}
                  </span>
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    {t("page.scenarioContainerDesc")}
                  </p>
                </div>
              </Card>
            </Col>
            <Col xs={24} sm={12} md={12}>
              <Card
                hoverable
                className="h-full bg-white dark:bg-slate-800 border-0 shadow-sm hover:shadow-md transition-all duration-300 rounded-xl"
                styles={{ body: { padding: '20px' } }}
              >
                <div className="flex flex-col items-center text-center">
                  <div className="flex items-center justify-center w-14 h-14 bg-gradient-to-br from-violet-500 to-violet-600 rounded-xl mb-4">
                    <Server className="h-7 w-7 text-white" />
                  </div>
                  <span className="text-lg font-semibold text-slate-900 dark:text-white mb-2">
                    {t("page.scenarioVM")}
                  </span>
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    {t("page.scenarioVMDesc")}
                  </p>
                </div>
              </Card>
            </Col>
          </Row>
        </motion.div>
      </section>

      {/* Core capabilities: natural language, multi-scenario, elastic scaling, security */}
      <motion.section
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, delay: 0.7 }}
        className="w-full mt-8 max-w-5xl py-4 px-8"
      >
        <motion.h3
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.8 }}
          className="text-xl font-bold text-slate-900 dark:text-white mb-6 text-center"
        >
          {t("page.coreCapabilities")}
        </motion.h3>
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.9 }}
        >
          <Row gutter={[20, 20]}>
            <Col xs={24} sm={12}>
              <Card
                hoverable
                className="h-full border border-slate-200 dark:border-slate-700 hover:shadow-md hover:border-purple-200 dark:hover:border-purple-900/30 transition-all duration-300"
              >
                <Card.Meta
                  avatar={
                    <div className="flex items-center justify-center w-12 h-12 bg-purple-100 dark:bg-purple-900/30 rounded-full">
                      <Bot className="h-6 w-6 text-purple-600 dark:text-purple-400" />
                    </div>
                  }
                  title={<span className="text-base font-semibold">{t("page.capabilityNatural")}</span>}
                  description={
                    <p className="text-sm text-slate-600 dark:text-slate-300 mt-1">
                      {t("page.capabilityNaturalDesc")}
                    </p>
                  }
                />
              </Card>
            </Col>
            <Col xs={24} sm={12}>
              <Card
                hoverable
                className="h-full border border-slate-200 dark:border-slate-700 hover:shadow-md hover:border-blue-200 dark:hover:border-blue-900/30 transition-all duration-300"
              >
                <Card.Meta
                  avatar={
                    <div className="flex items-center justify-center w-12 h-12 bg-blue-100 dark:bg-blue-900/30 rounded-full">
                      <Globe className="h-6 w-6 text-blue-600 dark:text-blue-400" />
                    </div>
                  }
                  title={<span className="text-base font-semibold">{t("page.capabilityMultiScenario")}</span>}
                  description={
                    <p className="text-sm text-slate-600 dark:text-slate-300 mt-1">
                      {t("page.capabilityMultiScenarioDesc")}
                    </p>
                  }
                />
              </Card>
            </Col>
            <Col xs={24} sm={12}>
              <Card
                hoverable
                className="h-full border border-slate-200 dark:border-slate-700 hover:shadow-md hover:border-green-200 dark:hover:border-green-900/30 transition-all duration-300"
              >
                <Card.Meta
                  avatar={
                    <div className="flex items-center justify-center w-12 h-12 bg-green-100 dark:bg-green-900/30 rounded-full">
                      <Zap className="h-6 w-6 text-green-600 dark:text-green-400" />
                    </div>
                  }
                  title={<span className="text-base font-semibold">{t("page.capabilityElastic")}</span>}
                  description={
                    <p className="text-sm text-slate-600 dark:text-slate-300 mt-1">
                      {t("page.capabilityElasticDesc")}
                    </p>
                  }
                />
              </Card>
            </Col>
            <Col xs={24} sm={12}>
              <Card
                hoverable
                className="h-full border border-slate-200 dark:border-slate-700 hover:shadow-md hover:border-amber-200 dark:hover:border-amber-900/30 transition-all duration-300"
              >
                <Card.Meta
                  avatar={
                    <div className="flex items-center justify-center w-12 h-12 bg-amber-100 dark:bg-amber-900/30 rounded-full">
                      <Unplug className="h-6 w-6 text-amber-600 dark:text-amber-400" />
                    </div>
                  }
                  title={<span className="text-base font-semibold">{t("page.capabilitySecure")}</span>}
                  description={
                    <p className="text-sm text-slate-600 dark:text-slate-300 mt-1">
                      {t("page.capabilitySecureDesc")}
                    </p>
                  }
                />
              </Card>
            </Col>
          </Row>
        </motion.div>
      </motion.section>
    </div>
  );
}
