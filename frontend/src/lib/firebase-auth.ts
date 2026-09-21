export type AuthConfig =
  | { mode: "api_key" }
  | {
      mode: "firebase";
      firebase_web_api_key: string;
      firebase_project_id: string;
    };

export type FirebaseSession = {
  idToken: string;
  refreshToken: string;
  expiresAt: number;
};

function lifetime(value: string | number | undefined) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 60 && parsed <= 7200 ? parsed : 3600;
}

export async function loadAuthConfig(): Promise<AuthConfig> {
  const response = await fetch("/auth/config", {
    cache: "no-store",
    signal: AbortSignal.timeout(10000),
  });
  if (!response.ok)
    throw new Error("Authentication configuration is unavailable.");
  const payload = (await response.json()) as AuthConfig;
  if (payload.mode !== "api_key" && payload.mode !== "firebase")
    throw new Error("Authentication configuration is invalid.");
  return payload;
}

export async function signInWithFirebase(
  apiKey: string,
  email: string,
  password: string,
): Promise<FirebaseSession> {
  const response = await fetch(
    `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${encodeURIComponent(apiKey)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: email.trim(),
        password,
        returnSecureToken: true,
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    },
  );
  const payload = (await response.json().catch(() => ({}))) as {
    idToken?: string;
    refreshToken?: string;
    expiresIn?: string;
  };
  if (!response.ok || !payload.idToken || !payload.refreshToken)
    throw new Error("Email or password was not accepted.");
  return {
    idToken: payload.idToken,
    refreshToken: payload.refreshToken,
    expiresAt: Date.now() + lifetime(payload.expiresIn) * 1000,
  };
}

export async function refreshFirebaseSession(
  apiKey: string,
  refreshToken: string,
): Promise<FirebaseSession> {
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    refresh_token: refreshToken,
  });
  const response = await fetch(
    `https://securetoken.googleapis.com/v1/token?key=${encodeURIComponent(apiKey)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    },
  );
  const payload = (await response.json().catch(() => ({}))) as {
    id_token?: string;
    refresh_token?: string;
    expires_in?: string;
  };
  if (!response.ok || !payload.id_token || !payload.refresh_token)
    throw new Error("Your secure session has expired. Sign in again.");
  return {
    idToken: payload.id_token,
    refreshToken: payload.refresh_token,
    expiresAt: Date.now() + lifetime(payload.expires_in) * 1000,
  };
}
