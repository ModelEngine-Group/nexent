"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Modal,
  Form,
  Input,
  Button,
  Typography,
  Space,
  Switch,
  Divider,
  App,
} from "antd";
import {
  UserOutlined,
  LockOutlined,
  SafetyOutlined,
  KeyOutlined,
  CrownOutlined,
  FileTextOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/hooks/useAuth";
import { AuthFormValues } from "@/types/auth"
import { useAuthForm } from "@/hooks/useAuthForm";
import log from "@/lib/logger";

const { Text } = Typography;

export function RegisterModal() {
  const {
    isRegisterModalOpen,
    closeRegisterModal,
    openLoginModal,
    register,
    authServiceUnavailable,
  } = useAuth();
  const {
    form,
    isLoading,
    setIsLoading,
    emailError,
    setEmailError,
    resetForm,
  } = useAuthForm();
  const [passwordError, setPasswordError] = useState<{
    target: "password" | "confirmPassword" | "";
    message: string;
  }>({ target: "", message: "" });
  const [isAdminMode, setIsAdminMode] = useState(false);
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  const validateEmail = (email: string): boolean => {
    if (!email) return false;

    if (!email.includes("@")) return false;

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
  };

  const validatePassword = (password: string): boolean => {
    return !!(password && password.length >= 6);
  };

  const handleSubmit = async (values: AuthFormValues) => {
    setIsLoading(true);
    setEmailError(""); // Reset error state
    setPasswordError({ target: "", message: "" }); // Reset password error state

    if (!validateEmail(values.email)) {
      const errorMsg = t("auth.invalidEmailFormat");
      message.error(errorMsg);
      setEmailError(errorMsg);
      setIsLoading(false);
      return;
    }

    if (!validatePassword(values.password)) {
      const errorMsg = t("auth.passwordMinLength");
      message.error(errorMsg);
      setPasswordError({ target: "password", message: errorMsg });
      form.setFields([
        {
          name: "password",
          errors: [errorMsg],
          value: values.password,
        },
      ]);
      setIsLoading(false);
      return;
    }

    try {
      await register(
        values.email,
        values.password,
        isAdminMode,
        values.inviteCode
      );

      // Reset form and clear error states
      resetForm();
      setIsAdminMode(false);
    } catch (error: any) {
      log.error("Registration error details:", error);

      if (error?.detail && Array.isArray(error.detail)) {
        const validationError = error.detail[0];

        if (validationError.loc && validationError.loc.includes("email")) {
          const errorMsg = t("auth.invalidEmailFormat");
          message.error(errorMsg);
          setEmailError(errorMsg);
          form.setFields([
            {
              name: "email",
              errors: [errorMsg],
              value: values.email,
            },
          ]);
          setIsLoading(false);
          return;
        }

        if (validationError.loc && validationError.loc.includes("password")) {
          const errorMsg = t("auth.passwordMinLength");
          message.error(errorMsg);
          setPasswordError({ target: "password", message: errorMsg });
          setIsLoading(false);
          return;
        }
      }

      // process the specific error type returned by the backend (based on HTTP status code and error_type)
      const httpStatusCode = error?.code;
      const errorType = error?.message;

      // HTTP 409 Conflict
      if (httpStatusCode === 409 || errorType === "EMAIL_ALREADY_EXISTS") {
        const errorMsg = t("auth.emailAlreadyExists");
        message.error(errorMsg);
        setEmailError(errorMsg);
        form.setFields([
          {
            name: "email",
            errors: [errorMsg],
            value: values.email,
          },
        ]);
      }
      // HTTP 406 Not Acceptable
      else if (httpStatusCode === 406 || errorType === "WEAK_PASSWORD") {
        const errorMsg = t("auth.weakPassword");
        message.error(errorMsg);
        setPasswordError({ target: "password", message: errorMsg });
        form.setFields([
          {
            name: "password",
            errors: [errorMsg],
            value: values.password,
          },
        ]);
      }
      // Invite code not configured
      else if (errorType === "INVITE_CODE_NOT_CONFIGURED") {
        const errorMsg = t("auth.inviteCodeNotConfigured");
        message.error(errorMsg);
        form.setFields([
          {
            name: "inviteCode",
            errors: [errorMsg],
            value: values.inviteCode,
          },
        ]);
      } else if (errorType === "INVITE_CODE_REQUIRED") {
        const errorMsg = t("auth.inviteCodeRequired");
        message.error(errorMsg);
        form.setFields([
          {
            name: "inviteCode",
            errors: [errorMsg],
            value: values.inviteCode,
          },
        ]);
      } else if (errorType === "INVITE_CODE_INVALID") {
        const errorMsg = t("auth.inviteCodeInvalid");
        message.error(errorMsg);
        form.setFields([
          {
            name: "inviteCode",
            errors: [errorMsg],
            value: values.inviteCode,
          },
        ]);
      }
      // Invalid email format
      else if (errorType === "INVALID_EMAIL_FORMAT") {
        const errorMsg = t("auth.invalidEmailFormat");
        message.error(errorMsg);
        setEmailError(errorMsg);
        form.setFields([
          {
            name: "email",
            errors: [errorMsg],
            value: values.email,
          },
        ]);
      }
      // Registration service error
      else if (errorType === "REGISTRATION_SERVICE_ERROR" || httpStatusCode === 500) {
        const errorMsg = t("auth.registrationServiceError");
        message.error(errorMsg);
        setEmailError(errorMsg);
      }
      // Network error
      else if (errorType === "NETWORK_ERROR") {
        const errorMsg = t("auth.networkError");
        message.error(errorMsg);
        setEmailError(errorMsg);
      }
      // Auth service unavailable
      else if (httpStatusCode === 503 || errorType === "AUTH_SERVICE_UNAVAILABLE") {
        const errorMsg = t("auth.authServiceUnavailable");
        message.error(errorMsg);
        setEmailError(errorMsg);
      }
      // Other unknown errors
      else {
        const errorMsg = error?.message || t("auth.unknownError");
        message.error(errorMsg);
        setPasswordError({ target: "", message: "" });
      }
    }

    setIsLoading(false);
  };

  const handleLoginClick = () => {
    resetForm();
    setPasswordError({ target: "", message: "" });
    setIsAdminMode(false);
    closeRegisterModal();
    openLoginModal();
  };

  const handleCancel = () => {
    resetForm();
    setPasswordError({ target: "", message: "" });
    setIsAdminMode(false);
    closeRegisterModal();
  };

  // Handle email input change - real-time email format validation
  const handleEmailInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;

    // Real-time email format validation
    if (value && !validateEmail(value)) {
      setEmailError(t("auth.invalidEmailFormat"));
    } else {
      setEmailError("");
    }
  };

  // Handle password input change - use new validation logic
  const handlePasswordChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;

    // Use validation function to check password strength
    if (value && !validatePassword(value)) {
      setPasswordError({
        target: "password",
        message: t("auth.passwordMinLength"),
      });
      return; // Exit early if password length is invalid
    }

    // Only check password match if length requirement is met
    setPasswordError({ target: "", message: "" });
    const confirmPassword = form.getFieldValue("confirmPassword");
    if (confirmPassword && confirmPassword !== value) {
      setPasswordError({
        target: "confirmPassword",
        message: t("auth.passwordsDoNotMatch"),
      });
    }
  };

  // Handle confirm password input change - use new validation logic
  const handleConfirmPasswordChange = (
    e: React.ChangeEvent<HTMLInputElement>
  ) => {
    const value = e.target.value;
    const password = form.getFieldValue("password");

    // First check if original password meets length requirement
    if (password && !validatePassword(password)) {
      setPasswordError({
        target: "password",
        message: t("auth.passwordMinLength"),
      });
      return;
    }

    // Then check password match
    if (value && value !== password) {
      setPasswordError({
        target: "confirmPassword",
        message: t("auth.passwordsDoNotMatch"),
      });
    } else {
      setPasswordError({ target: "", message: "" });
    }
  };

  return (
    <Modal
      title={
        <div className="text-center text-xl font-bold">
          {t("auth.registerTitle")}
        </div>
      }
      open={isRegisterModalOpen}
      onCancel={handleCancel}
      footer={null}
      width={400}
      centered
      forceRender
    >
      <Form
        id="register-form"
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        className="mt-6"
        autoComplete="off"
      >
        <Form.Item
          name="email"
          label={t("auth.emailLabel")}
          validateStatus={emailError ? "error" : ""}
          help={emailError}
          rules={[
            { required: true, message: t("auth.emailRequired") },
            {
              validator: (_, value) => {
                if (!value) return Promise.resolve();
                if (!validateEmail(value)) {
                  return Promise.reject(
                    new Error(t("auth.invalidEmailFormat"))
                  );
                }
                return Promise.resolve();
              },
            },
          ]}
        >
          <Input
            prefix={<UserOutlined className="text-gray-400" />}
            placeholder="your@email.com"
            size="large"
            onChange={handleEmailInputChange}
          />
        </Form.Item>

        <Form.Item
          name="password"
          label={t("auth.passwordLabel")}
          validateStatus={
            passwordError.target === "password" &&
            !form.getFieldError("password").length
              ? "error"
              : ""
          }
          help={
            form.getFieldError("password").length
              ? undefined
              : passwordError.target === "password"
              ? passwordError.message
              : authServiceUnavailable
              ? t("auth.authServiceUnavailable")
              : undefined
          }
          rules={[
            { required: true, message: t("auth.passwordRequired") },
            {
              validator: (_, value) => {
                if (!value) return Promise.resolve();
                if (!validatePassword(value)) {
                  return Promise.reject(new Error(t("auth.passwordMinLength")));
                }
                return Promise.resolve();
              },
            },
          ]}
          hasFeedback
        >
          <Input.Password
            id="register-password"
            prefix={<LockOutlined className="text-gray-400" />}
            placeholder={t("auth.passwordRequired")}
            size="large"
            onChange={handlePasswordChange}
          />
        </Form.Item>

        <Form.Item
          name="confirmPassword"
          label={t("auth.confirmPasswordLabel")}
          validateStatus={
            passwordError.target === "confirmPassword" &&
            !form.getFieldError("confirmPassword").length
              ? "error"
              : ""
          }
          help={
            form.getFieldError("confirmPassword").length
              ? undefined
              : passwordError.target === "confirmPassword"
              ? passwordError.message
              : authServiceUnavailable
              ? t("auth.authServiceUnavailable")
              : undefined
          }
          dependencies={["password"]}
          hasFeedback
          rules={[
            { required: true, message: t("auth.confirmPasswordRequired") },
            ({ getFieldValue }) => ({
              validator(_, value) {
                const password = getFieldValue("password");
                // First check password length using validation function
                if (password && !validatePassword(password)) {
                  setPasswordError({
                    target: "password",
                    message: t("auth.passwordMinLength"),
                  });
                  return Promise.reject(new Error(t("auth.passwordMinLength")));
                }
                // Then check password match
                if (!value || getFieldValue("password") === value) {
                  setPasswordError({ target: "", message: "" });
                  return Promise.resolve();
                }
                setPasswordError({
                  target: "confirmPassword",
                  message: t("auth.passwordsDoNotMatch"),
                });
                return Promise.reject(new Error(t("auth.passwordsDoNotMatch")));
              },
            }),
          ]}
        >
          <Input.Password
            id="register-confirm-password"
            prefix={<SafetyOutlined className="text-gray-400" />}
            placeholder={t("auth.confirmPasswordRequired")}
            size="large"
            onChange={handleConfirmPasswordChange}
          />
        </Form.Item>

        <Divider />

        <Form.Item className="mb-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CrownOutlined className="text-amber-500" />
              <span className="font-medium">{t("auth.adminAccount")}</span>
            </div>
            <Switch
              checked={isAdminMode}
              onChange={setIsAdminMode}
              checkedChildren={t("auth.admin")}
              unCheckedChildren={t("auth.user")}
            />
          </div>
          <Text type="secondary" className="text-sm mt-1 block">
            {t("auth.adminAccountDescription")}
          </Text>
        </Form.Item>

        {isAdminMode && (
          <>
            <div className="mb-4 p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg">
              <div className="text-sm text-blue-800 dark:text-blue-200">
                <div className="font-medium mb-2">
                  {t("auth.inviteCodeHint.title")}
                </div>
                <div className="space-y-1">
                  <div>
                    ✨ {t("auth.inviteCodeHint.step1")}
                    <a
                      href="https://github.com/ModelEngine-Group/nexent"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 dark:text-blue-400 hover:underline font-medium"
                    >
                      {t("auth.inviteCodeHint.projectLink")}
                    </a>
                    {t("auth.inviteCodeHint.starAction")}
                  </div>
                  <div>
                    💬 {t("auth.inviteCodeHint.step2")}
                    <a
                      href={t("auth.inviteCodeHint.contributionWallUrl")}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 dark:text-blue-400 hover:underline font-medium"
                    >
                      {t("auth.inviteCodeHint.contributionWallLink")}
                    </a>
                    {t("auth.inviteCodeHint.step2Action")}
                    <a
                      href={t("auth.inviteCodeHint.documentationUrl")}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="ml-2 text-blue-600 dark:text-blue-400 hover:underline"
                      title={t("auth.inviteCodeHint.viewDocumentation")}
                    >
                      <FileTextOutlined />
                    </a>
                  </div>
                  <div>
                    🎁 {t("auth.inviteCodeHint.step3")}
                    <a
                      href="http://nexent.tech/contact"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 dark:text-blue-400 hover:underline font-medium"
                    >
                      {t("auth.inviteCodeHint.communityLink")}
                    </a>
                    {t("auth.inviteCodeHint.step3Action")}
                  </div>
                </div>
              </div>
            </div>
            <Form.Item
              name="inviteCode"
              label={t("auth.inviteCodeLabel")}
              rules={[
                {
                  required: isAdminMode,
                  message: t("auth.inviteCodeRequired"),
                },
              ]}
            >
              <Input
                prefix={<KeyOutlined className="text-gray-400" />}
                placeholder={t("auth.inviteCodeRequired")}
                size="large"
              />
            </Form.Item>
          </>
        )}

        <Form.Item>
          <Button
            type="primary"
            htmlType="submit"
            loading={isLoading}
            block
            size="large"
            className="mt-2"
            disabled={authServiceUnavailable}
          >
            {isLoading
              ? isAdminMode
                ? t("auth.registeringAdmin")
                : t("auth.registering")
              : isAdminMode
              ? t("auth.registerAdmin")
              : t("auth.register")}
          </Button>
        </Form.Item>

        <div className="text-center">
          <Space>
            <Text type="secondary">{t("auth.hasAccount")}</Text>
            <Button type="link" onClick={handleLoginClick} className="p-0">
              {t("auth.loginNow")}
            </Button>
          </Space>
        </div>
      </Form>
    </Modal>
  );
}
