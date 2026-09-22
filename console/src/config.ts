// Where the console signs in. The appliance serves the console and the API from one origin, so the
// only thing that changes between installations is the realm of its Keycloak.
import type { OidcConfig } from "./auth/session";

export const CALLBACK_PATH = "/callback";

export function oidcConfig(): OidcConfig {
  const origin = window.location.origin;
  return {
    issuer: import.meta.env.VITE_OIDC_ISSUER ?? "http://127.0.0.1:8180/realms/argos",
    clientId: import.meta.env.VITE_OIDC_CLIENT_ID ?? "argos-console",
    redirectUri: `${origin}${CALLBACK_PATH}`,
  };
}
