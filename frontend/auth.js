// Cognito Hosted UI sign-in using OAuth 2.0 authorization code flow with PKCE.
// No client secret exists in the browser; tokens live in sessionStorage and
// disappear when the tab closes.

const Auth = (() => {
  const cfg = window.APP_CONFIG || {};
  const redirectUri = window.location.origin + "/";
  const KEY = "kb-assistant-tokens";

  const b64url = (bytes) =>
    btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

  function randomString(len = 64) {
    const bytes = new Uint8Array(len);
    crypto.getRandomValues(bytes);
    return b64url(bytes).slice(0, len);
  }

  async function sha256(text) {
    return crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  }

  function decode(jwt) {
    const part = jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const json = decodeURIComponent(
      atob(part).split("").map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2)).join("")
    );
    return JSON.parse(json);
  }

  function save(tokens) {
    const claims = decode(tokens.id_token);
    const stored = {
      idToken: tokens.id_token,
      refreshToken: tokens.refresh_token || load()?.refreshToken,
      expiresAt: claims.exp * 1000,
    };
    sessionStorage.setItem(KEY, JSON.stringify(stored));
    return stored;
  }

  function load() {
    try {
      return JSON.parse(sessionStorage.getItem(KEY));
    } catch {
      return null;
    }
  }

  async function tokenRequest(params) {
    const resp = await fetch(`${cfg.cognitoDomain}/oauth2/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ client_id: cfg.clientId, ...params }),
    });
    if (!resp.ok) throw new Error("Sign-in could not be completed. Try again.");
    return resp.json();
  }

  async function login() {
    const verifier = randomString(64);
    const state = randomString(24);
    sessionStorage.setItem("pkce-verifier", verifier);
    sessionStorage.setItem("pkce-state", state);
    const challenge = b64url(await sha256(verifier));
    const url = new URL(`${cfg.cognitoDomain}/oauth2/authorize`);
    url.search = new URLSearchParams({
      response_type: "code",
      client_id: cfg.clientId,
      redirect_uri: redirectUri,
      scope: "openid email profile",
      code_challenge_method: "S256",
      code_challenge: challenge,
      state,
    });
    window.location.assign(url.toString());
  }

  // Call once on page load. Returns true if the URL carried a login response.
  async function handleRedirect() {
    const params = new URLSearchParams(window.location.search);
    if (params.get("error")) {
      throw new Error(params.get("error_description") || "Sign-in was cancelled.");
    }
    const code = params.get("code");
    if (!code) return false;
    if (params.get("state") !== sessionStorage.getItem("pkce-state")) {
      throw new Error("Sign-in response didn't match this browser session. Sign in again.");
    }
    const tokens = await tokenRequest({
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri,
      code_verifier: sessionStorage.getItem("pkce-verifier"),
    });
    sessionStorage.removeItem("pkce-verifier");
    sessionStorage.removeItem("pkce-state");
    save(tokens);
    window.history.replaceState({}, document.title, redirectUri);
    return true;
  }

  // Returns a valid ID token, refreshing it if it expires within a minute.
  async function idToken() {
    const stored = load();
    if (!stored) return null;
    if (Date.now() < stored.expiresAt - 60_000) return stored.idToken;
    if (!stored.refreshToken) return null;
    try {
      const tokens = await tokenRequest({ grant_type: "refresh_token", refresh_token: stored.refreshToken });
      return save(tokens).idToken;
    } catch {
      sessionStorage.removeItem(KEY);
      return null;
    }
  }

  function user() {
    const stored = load();
    if (!stored) return null;
    const c = decode(stored.idToken);
    return { email: c.email || "", groups: c["cognito:groups"] || [] };
  }

  function logout() {
    sessionStorage.removeItem(KEY);
    const url = new URL(`${cfg.cognitoDomain}/logout`);
    url.search = new URLSearchParams({ client_id: cfg.clientId, logout_uri: redirectUri });
    window.location.assign(url.toString());
  }

  return { login, logout, handleRedirect, idToken, user };
})();
