"use client";

import React, { createContext, useContext, ReactNode } from "react";
import { useAuthentication } from "@/hooks/auth/useAuthentication";
import { AuthenticationContextType } from "@/types/auth";

/**
 * Authentication Context
 */
const AuthenticationContext = createContext<
  AuthenticationContextType | undefined
>(undefined);

/**
 * Authentication Provider Component
 * Provides authentication state and methods to the component tree
 */
export function AuthenticationProvider({ children }: { children?: ReactNode }) {
  const authValue = useAuthentication();

  return (
    <AuthenticationContext.Provider value={authValue}>
      {children}
    </AuthenticationContext.Provider>
  );
}

/**
 * Hook to use authentication context
 */
export function useAuthenticationContext(): AuthenticationContextType {
  const context = useContext(AuthenticationContext);
  if (context === undefined) {
    throw new Error(
      "useAuthenticationContext must be used within an AuthenticationProvider"
    );
  }
  return context;
}

// Export context for advanced use cases
export { AuthenticationContext };
