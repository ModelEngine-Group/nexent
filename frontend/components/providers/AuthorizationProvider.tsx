"use client";

import React, { createContext, useContext, ReactNode } from "react";
import { useAuthorization } from "@/hooks/auth/useAuthorization";
import { AuthorizationContextType } from "@/types/auth";

/**
 * Authorization Context
 */
const AuthorizationContext = createContext<
  AuthorizationContextType | undefined
>(undefined);

/**
 * Authorization Provider Component
 * Provides authorization state and methods to the component tree
 */
export function AuthorizationProvider({ children }: { children?: ReactNode }) {
  const authzValue = useAuthorization();

  return (
    <AuthorizationContext.Provider value={authzValue}>
      {children}
    </AuthorizationContext.Provider>
  );
}

/**
 * Hook to use authorization context
 */
export function useAuthorizationContext(): AuthorizationContextType {
  const context = useContext(AuthorizationContext);
  if (context === undefined) {
    throw new Error(
      "useAuthorizationContext must be used within an AuthorizationProvider"
    );
  }
  return context;
}

// Export context for advanced use cases
export { AuthorizationContext };
