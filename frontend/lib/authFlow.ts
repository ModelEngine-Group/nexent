let explicitLogoutInProgress = false;

export const authFlowState = {
  beginExplicitLogout: (): void => {
    explicitLogoutInProgress = true;
  },

  endExplicitLogout: (): void => {
    explicitLogoutInProgress = false;
  },

  isExplicitLogoutInProgress: (): boolean => explicitLogoutInProgress,
};
