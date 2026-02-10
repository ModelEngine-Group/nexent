"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { usePathname, useRouter } from "next/navigation";
import {
  Modal,
  Form,
  Input,
  Button,
  Typography,
  Space,
  Switch,
  App,
  Popover,
} from "antd";
import {
  UserRound,
  LockKeyhole,
  ShieldCheck,
  KeyRound,
  BookMarked,
  HelpCircle,
  Users,
} from "lucide-react";

import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { AuthFormValues } from "@/types/auth";
import { getEffectiveRoutePath } from "@/lib/auth";
import log from "@/lib/logger";

const { Text } = Typography;

export function RegisterModal() {
  const {
    isRegisterModalOpen,
    isAuthenticated,
    closeRegisterModal,
    openLoginModal,
    register,
    authServiceUnavailable,
  } = useAuthenticationContext();
  const { isSpeedMode } = useDeployment();

  const router = useRouter();
  const pathname = usePathname();
  const [form] = Form.useForm<AuthFormValues>();
  const [isLoading, setIsLoading] = useState(false);
  const [emailError, setEmailError] = useState("");
  const [passwordError, setPasswordError] = useState<{
    target: "password" | "confirmPassword" | "";
    message: string;
  }>({ target: "", message: "" });
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

  const resetForm = () => {
    setEmailError("");
    setPasswordError({ target: "", message: "" });
    form.resetFields();
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
        values.inviteCode,
        true,
      );

      // Reset form and clear error states
      resetForm();
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
      else if (
        errorType === "REGISTRATION_SERVICE_ERROR" ||
        httpStatusCode === 500
      ) {
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
      else if (
        httpStatusCode === 503 ||
        errorType === "AUTH_SERVICE_UNAVAILABLE"
      ) {
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
    closeRegisterModal();
    openLoginModal();
  };

  const handleCancel = () => {
    resetForm();
    setPasswordError({ target: "", message: "" });
    closeRegisterModal();

    // If user manually cancels registration from a protected page,
    // redirect back to home instead of keeping them on the restricted page
    if (!isAuthenticated && !isSpeedMode) {
      const effectivePath = pathname ? getEffectiveRoutePath(pathname) : "/";
      if (effectivePath !== "/") {
        router.push("/");
      }
    }
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
        <div className="text-center text-xl font-bold mt-3">
          {t("auth.registerTitle")}
        </div>
      }
      open={isRegisterModalOpen}
      onCancel={handleCancel}
      footer={null}
      width={420}
      centered
      forceRender
    >
      <div className="relative bg-white p-4 rounded-2xl">
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
              prefix={<UserRound className="text-gray-400" size={16} />}
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
              prefix={<LockKeyhole className="text-gray-400" size={16} />}
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
              prefix={<ShieldCheck className="text-gray-400" size={16} />}
              placeholder={t("auth.confirmPasswordRequired")}
              size="large"
              onChange={handleConfirmPasswordChange}
            />
          </Form.Item>

          <Form.Item
            name="inviteCode"
            label={t("auth.inviteCodeLabel")}
            rules={[{ required: true, message: t("auth.inviteCodeRequired") }]}
          >
            <Input
              prefix={<KeyRound className="text-gray-400" size={16} />}
              placeholder={t("auth.inviteCodePlaceholder")}
              size="large"
            />
          </Form.Item>

          <Form.Item>
            <Popover
              content={
                <div className="max-w-sm">
                  {/* Method 1: Open Source Contribution */}
                  <div className="bg-white dark:bg-gray-800 rounded-lg p-3 mb-3">
                    <div className="font-medium text-sm text-gray-900 dark:text-gray-100 mb-2">
                      {t("auth.inviteCodeHint.method1.title")}
                    </div>
                    <div className="space-y-2">
                      <div className="flex items-start">
                        <span className="mr-1 leading-none">✨</span>
                        <div className="text-sm text-gray-600 dark:text-gray-400">
                          {t("auth.inviteCodeHint.step1")}
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
                      </div>
                      <div className="flex items-start">
                        <span className="mr-1 leading-none">💬</span>
                        <div className="text-sm text-gray-600 dark:text-gray-400">
                          {t("auth.inviteCodeHint.step2")}
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
                            className="ml-1 text-blue-600 dark:text-blue-400 hover:underline inline-flex items-center"
                            title={t("auth.inviteCodeHint.viewDocumentation")}
                          >
                            <BookMarked size={16} />
                          </a>
                        </div>
                      </div>
                      <div className="flex items-start">
                        <span className="mr-1 leading-none">🎁</span>
                        <div className="text-sm text-gray-600 dark:text-gray-400">
                          {t("auth.inviteCodeHint.step3")}
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

                  {/* Method 2: Contact Tenant Administrator */}
                  <div className="bg-white dark:bg-gray-800 rounded-lg p-3">
                    <div className="font-medium text-sm text-gray-900 dark:text-gray-100 mb-2">
                      {t("auth.inviteCodeHint.method2.title")}
                    </div>
                    <div className="space-y-2">
                      <div className="flex items-start">
                        <Users size={16} className="text-blue-600 dark:text-blue-400 mr-1 mt-0.5" />
                        <div className="text-sm text-gray-600 dark:text-gray-400">
                          {t("auth.inviteCodeHint.method2.description")}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              }
              title={t("auth.inviteCodeHint.popoverTitle")}
              trigger="hover"
              mouseEnterDelay={0.3}
              overlayClassName="max-w-xs"
            >
              <div className="flex items-center text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 cursor-pointer text-sm">
                <HelpCircle size={16} className="mr-1" />
                {t("auth.inviteCodeHint.howToGetCode")}
              </div>
            </Popover>
          </Form.Item>


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
              {isLoading? t("auth.registering"): t("auth.register")}
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
      </div>
    </Modal>
  );
}
