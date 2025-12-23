"use client";

import { useTranslation, Trans } from "react-i18next";
import { Modal, Button } from "antd";

interface AuthDialogsProps {
  loginPromptOpen: boolean;
  adminPromptOpen: boolean;
  onCloseLoginPrompt: () => void;
  onCloseAdminPrompt: () => void;
  onLoginClick: () => void;
  onRegisterClick: () => void;
}

/**
 * Authentication dialogs component
 * Contains login prompt and admin prompt modals
 */
export function AuthDialogs({
  loginPromptOpen,
  adminPromptOpen,
  onCloseLoginPrompt,
  onCloseAdminPrompt,
  onLoginClick,
  onRegisterClick,
}: AuthDialogsProps) {
  const { t } = useTranslation("common");

  return (
    <>
      {/* Login prompt dialog */}
      <Modal
        title={t("page.loginPrompt.title")}
        open={loginPromptOpen}
        onCancel={onCloseLoginPrompt}
        footer={[
          <Button
            key="register"
            variant="link"
            onClick={onRegisterClick}
            className="bg-white mr-2"
          >
            {t("page.loginPrompt.register")}
          </Button>,
          <Button
            key="login"
            onClick={onLoginClick}
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
                ⭐️ Nexent is still growing, please help me by starring on
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

      {/* Admin prompt dialog */}
      <Modal
        title={t("page.adminPrompt.title")}
        open={adminPromptOpen}
        onCancel={onCloseAdminPrompt}
        footer={[
          <Button
            key="register"
            variant="link"
            onClick={onRegisterClick}
            className="bg-white mr-2"
          >
            {t("page.loginPrompt.register")}
          </Button>,
          <Button
            key="login"
            onClick={onLoginClick}
            className="bg-blue-600 text-white hover:bg-blue-700"
          >
            {t("page.loginPrompt.login")}
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
                ⭐️ Nexent is still growing, please help me by starring on
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
                💡 Want to become an administrator? Please visit the
                <a
                  href="http://nexent.tech/contact"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:text-blue-700 font-bold"
                >
                  official contact page
                </a>
                to apply for an administrator account.
              </Trans>
            </p>
          </div>
          <br />
        </div>
      </Modal>
    </>
  );
}

