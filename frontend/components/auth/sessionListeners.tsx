'use client';

import { useEffect, useRef } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { App, Modal } from 'antd';
import { ExclamationCircleOutlined } from '@ant-design/icons';
import { authService } from '@/services/authService';
import { EVENTS } from '@/types/auth';
import { useTranslation } from 'react-i18next';
import { useAuth } from '@/hooks/useAuth';

/**
 * Session management component
 * Handles session expiration, session refresh and other functions
 */
export function SessionListeners() {
  const router = useRouter();
  const pathname = usePathname();
  const { t } = useTranslation('common');
  const { openLoginModal, setIsFromSessionExpired, logout, isSpeedMode } = useAuth();
  const { modal } = App.useApp();
  const modalShownRef = useRef<boolean>(false);

  /**
   * Show "Login Expired" confirmation modal
   * This function handles debounce logic to prevent modal from appearing repeatedly
   */
  const showSessionExpiredModal = () => {
    // If already shown, return directly
    if (modalShownRef.current) return;
    modalShownRef.current = true;

    modal.confirm({
      title: t('login.expired.title'),
      icon: <ExclamationCircleOutlined />,
      content: t('login.expired.content'),
      okText: t('login.expired.okText'),
      cancelText: t('login.expired.cancelText'),
      closable: false,
      async onOk() {
        try {
          await logout(); // Log out first
        } finally {
          // Mark the source as session expired
          setIsFromSessionExpired(true);
          Modal.destroyAll();
          openLoginModal();
          setTimeout(() => (modalShownRef.current = false), 500);
        }
      },
      async onCancel() {
        try {
          await logout();
        } finally {
          router.push('/');
          setTimeout(() => (modalShownRef.current = false), 500);
        }
      }
    });
  };

  // Listen for events after successful login, reset modalShown state
  useEffect(() => {
    const handleModalClosed = () => {
      modalShownRef.current = false;
    };

    // Add event listener
    document.addEventListener('modalClosed', handleModalClosed);

    // Cleanup function
    return () => {
      document.removeEventListener('modalClosed', handleModalClosed);
    };
  }, []);

  // Listen for session expiration events
  useEffect(() => {
    const handleSessionExpired = (event: CustomEvent) => {
      // Directly call the wrapper function
      showSessionExpiredModal();
    };

    // Add event listener
    window.addEventListener(EVENTS.SESSION_EXPIRED, handleSessionExpired as EventListener);

    // Cleanup function
    return () => {
      window.removeEventListener(EVENTS.SESSION_EXPIRED, handleSessionExpired as EventListener);
    };
  // Remove confirm from dependency array to avoid duplicate registration due to function reference changes
  }, [router, pathname, openLoginModal, setIsFromSessionExpired, modal]);

  // When component first mounts, if no local session is found, show modal immediately
  useEffect(() => {
    // Skip in speed mode
    if (isSpeedMode) return;
    if (typeof window !== 'undefined') {
      const localSession = localStorage.getItem('session'); 
      if (!localSession) {
        showSessionExpiredModal();
      }
    }
    // Only run once on mount
  }, []);

  // Session status check
  useEffect(() => {
    // Skip in speed mode
    if (isSpeedMode) return;
    // Check session status on first load
    const checkSession = async () => {
      try {
        // Try to get current session
        const session = await authService.getSession();
        if (!session) {
          window.dispatchEvent(new CustomEvent(EVENTS.SESSION_EXPIRED, {
            detail: { message: "登录已过期，请重新登录" }
          }));
        }
      } catch (error) {
        console.error('Error checking session status:', error);
      }
    };

    checkSession();
  }, [pathname]);

  // This component doesn't render UI elements
  return null;
} 