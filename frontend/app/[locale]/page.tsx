"use client";

import { useState, useEffect } from "react";
import { useTranslation, Trans } from "react-i18next";
import {
  Bot,
  Globe,
  Zap,
  MessagesSquare,
  Unplug,
  TextQuote,
  AlertTriangle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import Link from "next/link";
import { AvatarDropdown } from "@/components/auth/avatarDropdown";
import { LoginModal } from "@/components/auth/loginModal";
import { RegisterModal } from "@/components/auth/registerModal";
import { useAuth } from "@/hooks/useAuth";
import { Modal, ConfigProvider, Dropdown } from "antd";
import { motion } from "framer-motion";
import {APP_VERSION, languageOptions } from "@/const/constants";
import { useLanguageSwitch } from "@/lib/language";
import { HEADER_CONFIG, FOOTER_CONFIG } from "@/const/layoutConstants";
import { DownOutlined } from "@ant-design/icons";
import { versionService } from "@/services/versionService";
import log from "@/lib/logger";

export default function Home() {
  const [mounted, setMounted] = useState(false);
  const { currentLanguage, handleLanguageChange } = useLanguageSwitch();

  // Prevent hydration errors
  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return null;
  }

  return (
    <ConfigProvider getPopupContainer={() => document.body}>
      <FrontpageContent />
    </ConfigProvider>
  );

  function FrontpageContent() {
    const { t } = useTranslation("common");
    const {
      user,
      isLoading: userLoading,
      openLoginModal,
      openRegisterModal,
      isSpeedMode,
    } = useAuth();
    const [loginPromptOpen, setLoginPromptOpen] = useState(false);
    const [adminRequiredPromptOpen, setAdminRequiredPromptOpen] =
      useState(false);
    const [appVersion, setAppVersion] = useState<string>("");

    // Get app version on mount
    useEffect(() => {
      const fetchAppVersion = async () => {
        try {
          const version = await versionService.getAppVersion();
          setAppVersion(version);
        } catch (error) {
          log.error("Failed to fetch app version:", error);
          setAppVersion(APP_VERSION); // Fallback
        }
      };

      fetchAppVersion();
    }, []);

    // Handle operations that require login
    const handleAuthRequired = (e: React.MouseEvent) => {
      if (!user) {
        e.preventDefault();
        setLoginPromptOpen(true);
      }
    };

    // Confirm login dialog
    const handleCloseLoginPrompt = () => {
      setLoginPromptOpen(false);
    };

    // Handle login button click
    const handleLoginClick = () => {
      setLoginPromptOpen(false);
      openLoginModal();
    };

    // Handle register button click
    const handleRegisterClick = () => {
      setLoginPromptOpen(false);
      openRegisterModal();
    };

    // Handle operations that require admin privileges
    const handleAdminRequired = (e: React.MouseEvent) => {
      if (user?.role !== "admin") {
        e.preventDefault();
        setAdminRequiredPromptOpen(true);
      }
    };

    // Close admin prompt dialog
    const handleCloseAdminPrompt = () => {
      setAdminRequiredPromptOpen(false);
    };

    return (
      <div className="min-h-screen flex flex-col bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800">
        {/* Top navigation bar */}
        <header
          className="w-full py-4 px-6 flex items-center justify-between border-b border-slate-200 dark:border-slate-700 bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm fixed top-0 z-10"
          style={{ height: HEADER_CONFIG.HEIGHT }}
        >
          <div className="flex items-center gap-2">
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
          </div>
          <div className="hidden md:flex items-center gap-6">
            {/* Github button */}
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
            {/* ModelEngine link always visible */}
            <Link
              href="http://modelengine-ai.net"
              className="text-sm font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white transition-colors"
            >
              ModelEngine
            </Link>
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
                {languageOptions.find((o) => o.value === currentLanguage)
                  ?.label || currentLanguage}
                <DownOutlined className="text-[10px]" />
              </a>
            </Dropdown>
            {/* Login status toggle display - only shown in full version */}
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
          {/* Right hamburger button reserved for mobile version */}
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

        {/* Main content */}
        <main className="flex-1 pt-8 pb-8 flex flex-col justify-center my-8">
          {/* Hero area */}
          <section className="relative w-full py-10 flex flex-col items-center justify-center text-center px-4">
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

            {/* Two parallel buttons */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.8, delay: 0.4 }}
              className="flex flex-col sm:flex-row gap-4"
            >
              <Link href={user ? "/chat" : "#"} onClick={handleAuthRequired}>
                <Button className="bg-blue-600 hover:bg-blue-700 text-white px-8 py-6 rounded-full text-lg font-medium shadow-lg hover:shadow-xl transition-all duration-300 group">
                  <Bot className="mr-2 h-5 w-5 group-hover:animate-pulse" />
                  {t("page.startChat")}
                </Button>
              </Link>

              <Link
                href={user?.role === "admin" ? "/setup" : "#"}
                onClick={handleAdminRequired}
              >
                <Button className="bg-blue-600 hover:bg-blue-700 text-white px-8 py-6 rounded-full text-lg font-medium shadow-lg hover:shadow-xl transition-all duration-300 group">
                  <Zap className="mr-2 h-5 w-5 group-hover:animate-pulse" />
                  {t("page.quickConfig")}
                </Button>
              </Link>
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
            className="max-w-7xl mx-auto px-4 mb-6"
          >
            <motion.h3
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.8, delay: 0.7 }}
              className="text-2xl font-bold text-slate-900 dark:text-white mb-8 text-center"
            >
              {t("page.coreFeatures")}
            </motion.h3>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.8, delay: 0.8 }}
              className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 items-stretch"
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
                  <MessagesSquare
                    key={5}
                    className="h-8 w-8 text-purple-500"
                  />,
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
                        icons[index] || (
                          <Bot className="h-8 w-8 text-blue-500" />
                        )
                      }
                      title={feature.title}
                      description={feature.description}
                    />
                  </motion.div>
                );
              })}
            </motion.div>
          </motion.section>
        </main>

        {/* Footer */}
        <footer
          className="w-full py-4 px-4 flex items-center justify-center border-t border-slate-200 dark:border-slate-700 bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm"
          style={{ height: FOOTER_CONFIG.HEIGHT }}
        >
          <div className="max-w-7xl mx-auto w-full">
            <div className="flex flex-col md:flex-row justify-between items-center h-full">
              <div className="flex items-center gap-8">
                <span className="text-sm text-slate-900 dark:text-white">
                  {t("page.copyright", { year: new Date().getFullYear() })}
                  <span className="ml-1">· {appVersion || APP_VERSION}</span>
                </span>
              </div>
              <div className="flex items-center gap-6">
                <Link
                  href="https://github.com/nexent-hub/nexent?tab=License-1-ov-file#readme"
                  className="text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
                >
                  {t("page.termsOfUse")}
                </Link>
                <Link
                  href="http://nexent.tech/contact"
                  className="text-sm text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white transition-colors"
                >
                  {t("page.contactUs")}
                </Link>
                <Link
                  href="http://nexent.tech/about"
                  className="text-sm text-slate-600 dark:text-slate-300 dark:hover:text-white transition-colors"
                >
                  {t("page.aboutUs")}
                </Link>
              </div>
            </div>
          </div>
        </footer>

        {/* Login prompt dialog - only shown in full version */}
        {!isSpeedMode && (
          <Modal
            title={t("page.loginPrompt.title")}
            open={loginPromptOpen}
            onCancel={handleCloseLoginPrompt}
            footer={[
              <Button
                key="register"
                variant="link"
                onClick={handleRegisterClick}
                className="bg-white mr-2"
              >
                {t("page.loginPrompt.register")}
              </Button>,
              <Button
                key="login"
                onClick={handleLoginClick}
                className="bg-blue-600 text-white hover:bg-blue-700"
              >
                {t("page.loginPrompt.login")}
              </Button>,
            ]}
            centered
          >
            <div className="py-2">
              <h3 className="text-base font-medium mb-2">
                {t("page.loginPrompt.header")}
              </h3>
              <p className="text-gray-600 mb-3">
                {t("page.loginPrompt.intro")}
              </p>

              <div className="rounded-md mb-6 mt-3">
                <h3 className="text-base font-medium mb-1">
                  {t("page.loginPrompt.benefitsTitle")}
                </h3>
                <ul className="text-gray-600 pl-5 list-disc">
                  {(
                    t("page.loginPrompt.benefits", {
                      returnObjects: true,
                    }) as string[]
                  ).map((benefit, i) => (
                    <li key={i}>{benefit}</li>
                  ))}
                </ul>
              </div>

              <div className="mt-4">
                <p className="text-base font-medium">
                  <Trans i18nKey="page.loginPrompt.githubSupport">
                    ⭐️ Nexent is still growing, please help me by starring on{" "}
                    <a
                      href="https://github.com/ModelEngine-Group/nexent"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:text-blue-700 font-bold"
                    >
                      GitHub
                    </a>
                    , thank you.
                  </Trans>
                </p>
              </div>
              <br />

              <p className="text-gray-500 text-xs">
                {t("page.loginPrompt.noAccount")}
              </p>
            </div>
          </Modal>
        )}

        {/* Login and register modals - only shown in full version */}
        {!isSpeedMode && (
          <>
            <LoginModal />
            <RegisterModal />
          </>
        )}

        {/* Admin prompt dialog - only shown in full version */}
        {!isSpeedMode && (
          <Modal
            title={t("page.adminPrompt.title")}
            open={adminRequiredPromptOpen}
            onCancel={handleCloseAdminPrompt}
            footer={[
              <Button
                key="close"
                onClick={handleCloseAdminPrompt}
                className="bg-blue-600 text-white hover:bg-blue-700"
              >
                {t("page.adminPrompt.close")}
              </Button>,
            ]}
            centered
          >
            <div className="py-2">
              <p className="text-gray-600">{t("page.adminPrompt.intro")}</p>
            </div>
            <div className="py-2">
              <h3 className="text-base font-medium mb-2">
                {t("page.adminPrompt.unlockHeader")}
              </h3>
              <p className="text-gray-600 mb-3">
                {t("page.adminPrompt.unlockIntro")}
              </p>
              <div className="rounded-md mb-6 mt-3">
                <h3 className="text-base font-medium mb-1">
                  {t("page.adminPrompt.permissionsTitle")}
                </h3>
                <ul className="text-gray-600 pl-5 list-disc">
                  {(
                    t("page.adminPrompt.permissions", {
                      returnObjects: true,
                    }) as string[]
                  ).map((permission, i) => (
                    <li key={i}>{permission}</li>
                  ))}
                </ul>
              </div>
              <div className="mt-4">
                <p className="text-base font-medium">
                  <Trans i18nKey="page.adminPrompt.githubSupport">
                    ⭐️ Nexent is still growing, please help me by starring on{" "}
                    <a
                      href="https://github.com/ModelEngine-Group/nexent"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:text-blue-700 font-bold"
                    >
                      GitHub
                    </a>
                    , thank you.
                  </Trans>
                  <br />
                  <br />
                  <Trans i18nKey="page.adminPrompt.becomeAdmin">
                    💡 Want to become an administrator? Please visit the{" "}
                    <a
                      href="http://nexent.tech/contact"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:text-blue-700 font-bold"
                    >
                      official contact page
                    </a>{" "}
                    to apply for an administrator account.
                  </Trans>
                </p>
              </div>
              <br />
            </div>
          </Modal>
        )}
      </div>
    );
  }
}

// Feature card component
interface FeatureCardProps {
  icon: React.ReactNode;
  title: string;
  description: string;
}

function FeatureCard({ icon, title, description }: FeatureCardProps) {
  return (
    <Card className="overflow-hidden border border-slate-200 dark:border-slate-700 transition-all duration-300 hover:shadow-md hover:border-blue-200 dark:hover:border-blue-900 group h-full">
      <CardContent className="p-6 h-full flex flex-col">
        <div className="mb-4 p-3 bg-slate-100 dark:bg-slate-800 rounded-full w-fit group-hover:bg-blue-100 dark:group-hover:bg-blue-900/30 transition-colors">
          {icon}
        </div>
        <h4 className="text-lg font-semibold text-slate-900 dark:text-white mb-2">
          {title}
        </h4>
        <p className="text-slate-600 dark:text-slate-300 flex-grow">
          {description}
        </p>
      </CardContent>
    </Card>
  );
}
