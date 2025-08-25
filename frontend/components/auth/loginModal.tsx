"use client"

import { useAuth } from "@/hooks/useAuth"
import { useAuthForm } from "@/hooks/useAuthForm"
import { Modal, Form, Input, Button, Typography, Space } from "antd"
import { UserOutlined, LockOutlined } from "@ant-design/icons"
import { EVENTS, STATUS_CODES } from "@/types/auth"
import { useTranslation } from "react-i18next"

const { Text } = Typography

/**
 * LoginModal Component
 * Handles user authentication through a modal interface
 * Supports both regular login and session expiration scenarios
 */
export function LoginModal() {
  // Authentication state and methods from useAuth hook
  const { isLoginModalOpen, closeLoginModal, openRegisterModal, login, isFromSessionExpired, setIsFromSessionExpired, authServiceUnavailable } = useAuth()
  
  // Form state and validation methods from useAuthForm hook
  const {
    form,
    isLoading,
    setIsLoading,
    emailError,
    passwordError,
    setEmailError,
    setPasswordError,
    handleEmailChange,
    handlePasswordChange,
    resetForm
  } = useAuthForm()
  
  // Internationalization hook for multi-language support
  const { t } = useTranslation('common');

  /**
   * Handles form submission for user login
   * @param values - Object containing email and password
   */
  const handleSubmit = async (values: { email: string; password: string }) => {
    // Clear previous error states
    setEmailError("")
    setPasswordError(false)
    setIsLoading(true)

    try {
      // Attempt to login with provided credentials
      await login(values.email, values.password)
      
      // Reset session expired flag after successful login
      setIsFromSessionExpired(false)
      
      // Reset modal control state to prevent session expired modal from triggering again
      // Small delay ensures proper state synchronization
      setTimeout(() => {
        document.dispatchEvent(new CustomEvent('modalClosed'))
      }, 200)
    } catch (error: any) {
      // Clear email error and set password error flag
      setEmailError("")
      setPasswordError(true)

      // Check if error is due to server timeout or auth service unavailability
      if (error?.code === STATUS_CODES.SERVER_ERROR || error?.code === STATUS_CODES.AUTH_SERVICE_UNAVAILABLE) {
        // Display server error message in password field
        form.setFields([
          {
            name: "password",
            errors: [t('auth.authServiceUnavailable')],
            value: values.password
          }
        ]);
      } else {
        // Display invalid credentials error in both fields
        form.setFields([
          {
            name: "email",
            errors: [""],
            value: values.email
          },
          {
            name: "password",
            errors: [t('auth.invalidCredentials')],
            value: values.password
          }
        ]);
      }
    } finally {
      // Always reset loading state
      setIsLoading(false)
    }
  }

  /**
   * Handles transition from login to registration modal
   * Resets form and opens registration modal
   */
  const handleRegisterClick = () => {
    resetForm()
    closeLoginModal()
    openRegisterModal()
  }

  /**
   * Handles modal cancellation
   * Resets form and handles session expiration scenarios
   */
  const handleCancel = () => {
    resetForm()
    closeLoginModal()

    // If login modal was opened due to session expiration, 
    // re-trigger the session expired event
    if (isFromSessionExpired) {
      setTimeout(() => {
        window.dispatchEvent(new CustomEvent(EVENTS.SESSION_EXPIRED, {
          detail: { message: t('auth.sessionExpired') }
        }));
      }, 100);
    }
  }

  return (
    <Modal
      title={<div className="text-center text-xl font-bold">{t('auth.loginTitle')}</div>}
      open={isLoginModalOpen}
      onCancel={handleCancel}
      footer={null}
      width={400}
      centered
      // Prevent modal from being closed by clicking mask or close button when session is expired
      maskClosable={!isFromSessionExpired}
      closable={!isFromSessionExpired}
    >
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
          label={t('auth.emailLabel')}
          validateStatus={emailError ? "error" : ""}
          help={emailError}
          rules={[
            { required: true, message: t('auth.emailRequired') }
          ]}
        >
          <Input
            prefix={<UserOutlined className="text-gray-400" />}
            placeholder={t('auth.emailPlaceholder')}
            onChange={handleEmailChange}
            size="large"
          />
        </Form.Item>

        {/* Password input field */}
        <Form.Item
          name="password"
          label={t('auth.passwordLabel')}
          validateStatus={passwordError ? "error" : ""}
          help={passwordError || authServiceUnavailable ? (authServiceUnavailable ? t('auth.authServiceUnavailable') : t('auth.invalidCredentials')) : ""}
          rules={[{ required: true, message: t('auth.passwordRequired') }]}
        >
          <Input.Password
            prefix={<LockOutlined className="text-gray-400" />}
            placeholder={t('auth.passwordRequired')}
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
            {isLoading ? t('auth.loggingIn') : t('auth.login')}
          </Button>
        </Form.Item>

        {/* Registration link section */}
        <div className="text-center">
          <Space>
            <Text type="secondary">{t('auth.noAccount')}</Text>
            <Button type="link" onClick={handleRegisterClick} className="p-0">
              {t('auth.registerNow')}
            </Button>
          </Space>
        </div>
      </Form>
    </Modal>
  )
} 