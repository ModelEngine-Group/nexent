import { authFlowState } from "@/lib/authFlow";
import { casService } from "@/services/casService";
import { oauthService } from "@/services/oauthService";

let redirectInProgress = false;
let oauthAutoLoginSuppressed = false;

const hasOAuthError = (): boolean => {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).has("oauth_error");
};

export const forcedLoginService = {
  suppressOAuthAutoLogin: (): void => {
    oauthAutoLoginSuppressed = true;
  },

  resetOAuthAutoLoginSuppression: (): void => {
    oauthAutoLoginSuppressed = false;
  },

  redirectIfNeeded: async (redirect?: string): Promise<boolean> => {
    if (redirectInProgress) return true;
    if (authFlowState.isExplicitLogoutInProgress()) return true;
    const oauthErrorAtStart = hasOAuthError();

    const casConfig = await casService.getConfig();
    if (redirectInProgress) return true;
    if (authFlowState.isExplicitLogoutInProgress()) return true;

    if (casConfig.enabled && casConfig.login_mode === "force") {
      redirectInProgress = true;
      casService.startLogin(redirect);
      return true;
    }

    if (oauthErrorAtStart || hasOAuthError()) {
      oauthAutoLoginSuppressed = true;
    }
    if (oauthAutoLoginSuppressed) return false;

    const oauthConfig = await oauthService.getConfig();
    if (redirectInProgress) return true;
    if (authFlowState.isExplicitLogoutInProgress()) return true;

    if (
      oauthConfig.enabled &&
      oauthConfig.login_mode === "force" &&
      oauthConfig.auto_login_provider
    ) {
      redirectInProgress = true;
      oauthService.startOAuthLogin(oauthConfig.auto_login_provider);
      return true;
    }

    return false;
  },
};
