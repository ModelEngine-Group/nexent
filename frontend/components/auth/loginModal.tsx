"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Form, Input, Button, Typography, Space } from "antd";
import { UserRound, LockKeyhole } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";

import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { getEffectiveRoutePath } from "@/lib/auth";
import log from "@/lib/logger";

const { Text } = Typography;

/**
 * LoginModal Component
 * Handles user authentication through a modal interface
 * Supports both regular login and session expiration scenarios
 */
export function LoginModal() {
  // Authentication state and methods from useAuth hook
  const {
    isLoginModalOpen,
    isAuthenticated,
    closeLoginModal,
    openRegisterModal,
    login,
    authServiceUnavailable,
  } = useAuthenticationContext();
  const { isSpeedMode } = useDeployment();

  const router = useRouter();
  const pathname = usePathname();
  const [form] = Form.useForm();
  const [isLoading, setIsLoading] = useState(false);
  const [emailError, setEmailError] = useState("");
  const [passwordError, setPasswordError] = useState(false);

  const resetForm = () => {
    setEmailError("");
    setPasswordError(false);
    form.resetFields();
  };

  const handleEmailChange = () => {
    if (emailError) {
      setEmailError("");
      form.setFields([
        {
          name: "email",
          errors: [],
        },
      ]);
    }
  };

  const handlePasswordChange = () => {
    if (passwordError) {
      setPasswordError(false);
    }
  };

  // Internationalization hook for multi-language support
  const { t } = useTranslation("common");

  /**
   * Handles form submission for user login
   * @param values - Object containing email and password
   */
  const handleSubmit = async (values: { email: string; password: string }) => {
    // Clear previous error states
    setEmailError("");
    setPasswordError(false);
    setIsLoading(true);

    try {
      // Attempt to login with provided credentials
      await login(values.email, values.password);

      setTimeout(() => {
        // Close the login modal after successful login
        closeLoginModal();
      }, 200);
    } catch (error: any) {
      log.error("Login failed", error);
      // Clear email error and set password error flag
      setEmailError("");
      setPasswordError(true);

      // Handle backend errors based on HTTP status code
      const httpStatusCode = error?.code;

      // Check if error is due to server timeout or auth service unavailability
      if (httpStatusCode === 500 || httpStatusCode === 503) {
        // Display server error message in password field
        form.setFields([
          {
            name: "password",
            errors: [t("auth.authServiceUnavailable")],
            value: values.password,
          },
        ]);
      } else if (httpStatusCode === 401) {
        // HTTP 401 Unauthorized - Invalid credentials
        form.setFields([
          {
            name: "email",
            errors: [""],
            value: values.email,
          },
          {
            name: "password",
            errors: [t("auth.invalidCredentials")],
            value: values.password,
          },
        ]);
      } else {
        // Display invalid credentials error for other cases
        form.setFields([
          {
            name: "email",
            errors: [""],
            value: values.email,
          },
          {
            name: "password",
            errors: [t("auth.invalidCredentials")],
            value: values.password,
          },
        ]);
      }
    } finally {
      // Always reset loading state
      setIsLoading(false);
    }
  };

  /**
   * Handles transition from login to registration modal
   * Resets form and opens registration modal
   */
  const handleRegisterClick = () => {
    resetForm();
    closeLoginModal();
    openRegisterModal();
  };

  /**
   * Handles modal cancellation
   * Resets form and handles session expiration scenarios
   */
  const handleCancel = () => {
    resetForm();
    closeLoginModal();

    // If user manually cancels login from a protected page,
    // redirect back to home instead of keeping them on the restricted page
    if (!isAuthenticated && !isSpeedMode) {
      const effectivePath = pathname ? getEffectiveRoutePath(pathname) : "/";
      if (effectivePath !== "/") {
        router.push("/");
      }
    }
  };

  return (
    <Modal
      title={
        <div className="text-center text-xl font-bold mt-3">
          {t("auth.loginTitle")}
        </div>
      }
      open={isLoginModalOpen}
      onCancel={handleCancel}
      footer={null}
      width={420}
      centered
      forceRender
      maskClosable={false}
      closable={true}
    >
      <div className="relative bg-white p-4 rounded-2xl">
        <Form
          id="login-form"
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          className="mt-6"
          autoComplete="off"
        >
          {/* Email input field */}
          <Form.Item
            name="email"
            label={t("auth.emailLabel")}
            validateStatus={emailError ? "error" : ""}
            help={emailError}
            rules={[{ required: true, message: t("auth.emailRequired") }]}
          >
            <Input
              prefix={<UserRound className="text-gray-400" size={16} />}
              placeholder={t("auth.emailPlaceholder")}
              onChange={handleEmailChange}
              size="large"
            />
          </Form.Item>

          {/* Password input field */}
          <Form.Item
            name="password"
            label={t("auth.passwordLabel")}
            validateStatus={passwordError ? "error" : ""}
            help={
              passwordError || authServiceUnavailable
                ? authServiceUnavailable
                  ? t("auth.authServiceUnavailable")
                  : t("auth.invalidCredentials")
                : ""
            }
            rules={[{ required: true, message: t("auth.passwordRequired") }]}
          >
            <Input.Password
              prefix={<LockKeyhole className="text-gray-400" size={16} />}
              placeholder={t("auth.passwordRequired")}
              onChange={handlePasswordChange}
              size="large"
              status={passwordError ? "error" : ""}
            />
          </Form.Item>

          {/* Submit button */}
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
              {isLoading ? t("auth.loggingIn") : t("auth.login")}
            </Button>
          </Form.Item>

          {/* Registration link section (hidden when opened from session expired flow) */}
          
            <div className="text-center">
              <Space>
                <Text type="secondary">{t("auth.noAccount")}</Text>
                <Button type="link" onClick={handleRegisterClick} className="p-0">
                  {t("auth.registerNow")}
                </Button>
              </Space>
            </div>

        </Form>
      </div>
    </Modal>
  );
}
