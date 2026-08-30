import type { AuthStatus } from "@/lib/auth";

/**
 * Browser projection of the backend auth status.
 *
 * `known` deliberately stays separate from `enabled`: a failed status request
 * is not proof that authentication is disabled. Deployment-wide controls must
 * remain closed until the browser has received an actual status response.
 */
export interface AuthStatusState {
  known: boolean;
  enabled: boolean;
  authenticated: boolean;
  isAdmin: boolean;
  canUploadCourseSources: boolean;
  loading: boolean;
}

export const INITIAL_AUTH_STATUS: AuthStatusState = {
  known: false,
  enabled: false,
  authenticated: false,
  isAdmin: false,
  canUploadCourseSources: false,
  loading: true,
};

export function projectAuthStatus(
  status: AuthStatus | null,
): AuthStatusState {
  if (!status) {
    return {
      ...INITIAL_AUTH_STATUS,
      loading: false,
    };
  }
  const enabled = Boolean(status.enabled);
  const authenticated = Boolean(status.authenticated);
  return {
    known: true,
    enabled,
    authenticated,
    isAdmin: status.role === "admin",
    canUploadCourseSources:
      !enabled || (authenticated && Boolean(status.course_source_uploads)),
    loading: false,
  };
}

/** Confirmed administrators and confirmed auth-disabled local runs manage the deployment. */
export function canManageDeployment(
  status: Pick<
    AuthStatusState,
    "known" | "loading" | "enabled" | "authenticated" | "isAdmin"
  >,
): boolean {
  return (
    status.known &&
    !status.loading &&
    (!status.enabled || (status.authenticated && status.isAdmin))
  );
}
