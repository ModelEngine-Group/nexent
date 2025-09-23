"use client";

import { useState, useEffect, useRef } from "react";

import { Form } from "antd";
import { AuthFormValues } from "@/types/auth";

export function useAuthForm() {
  const [form] = Form.useForm<AuthFormValues>();
  const [isLoading, setIsLoading] = useState(false);
  const [emailError, setEmailError] = useState("");
  const [passwordError, setPasswordError] = useState(false);
  const isMountedRef = useRef(true);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // Reset all errors
  const resetErrors = () => {
    setEmailError("");
    setPasswordError(false);
  };

  // Handle email input change
  const handleEmailChange = () => {
    if (!isMountedRef.current) return;
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

  // Handle password input change
  const handlePasswordChange = () => {
    if (!isMountedRef.current) return;
    if (passwordError) {
      setPasswordError(false);
    }
  };

  // Reset form
  const resetForm = () => {
    if (!isMountedRef.current) return;
    resetErrors();
    form.resetFields();
  };

  return {
    form,
    isLoading,
    setIsLoading,
    emailError,
    setEmailError,
    passwordError,
    setPasswordError,
    resetErrors,
    handleEmailChange,
    handlePasswordChange,
    resetForm,
  };
}
