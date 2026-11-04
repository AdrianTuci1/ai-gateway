import { useEffect, useState } from "react";

import {
  ApiError,
  consumeSessionExpired,
  getAuthConfig,
  googleLoginUrl,
  login,
  setSession,
  type AuthConfig,
} from "../api";
import { Icon } from "../components/Icon";

const SSO_ERRORS: Record<string, string> = {
  no_account: "No account matches that Google address. Request access first.",
  not_a_member: "That account is not a member of this workspace.",
  approval_pending: "Your access request is waiting for approval.",
  signup_rejected: "Your access request was rejected.",
  oidc_domain_not_allowed: "Sign in with an allowed Google account.",
  google_denied: "Google sign-in was cancelled.",
  oidc_unavailable: "Google sign-in is not configured on this server.",
};

function ssoErrorMessage(): string | null {
  if (typeof window === "undefined") return null;
  const code = new URLSearchParams(window.location.search).get("sso_error");
  if (!code) return null;
  return SSO_ERRORS[code] ?? "Google sign-in failed. Try again.";
}

function describeLoginError(caught: unknown): string {
  if (!(caught instanceof ApiError)) {
    return "Login failed. Check that the gateway is reachable.";
  }
  if (caught.message === "e-mail or password is incorrect") {
    return "E-mail or password is incorrect.";
  }
  if (caught.message === "endpoint does not exist") {
    return "Password sign-in is disabled on this server. Use Google sign-in or contact an administrator.";
  }
  if (caught.message === "user or workspace does not exist") {
    return "No account matches that workspace and e-mail. Request access first, or check the workspace slug.";
  }
  if (caught.message === "your access request is waiting for approval") {
    return "Your access request is waiting for approval. An owner or admin must approve it before you can sign in.";
  }
  if (caught.message === "your access request was rejected") {
    return "Your access request was rejected. Submit a new request or contact a workspace administrator.";
  }
  return caught.message;
}

export function Login({
  onDone,
  onSignup,
}: {
  onDone: () => void;
  onSignup: () => void;
}) {
  const [workspace, setWorkspace] = useState(localStorage.getItem("agw.last-workspace") ?? "");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [expired] = useState(consumeSessionExpired);
  const [ssoError] = useState(ssoErrorMessage);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getAuthConfig()
      .then(setConfig)
      .catch(() => setConfig({ password: true, google: false, dev: false }));
  }, []);

  useEffect(() => {
    const raw = window.location.hash.replace(/^#/, "");
    if (!raw) return;
    const params = new URLSearchParams(raw);
    const token = params.get("sso");
    if (!token) return;
    const signedInWorkspace = params.get("workspace") ?? workspace;
    const signedInEmail = params.get("email") ?? "";
    setSession(token, signedInWorkspace, signedInEmail);
    localStorage.setItem("agw.last-workspace", signedInWorkspace);
    window.history.replaceState(null, "", window.location.pathname);
    onDone();
  }, [onDone, workspace]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await login(workspace.trim(), email.trim(), password);
      setSession(result.token, workspace.trim(), email.trim());
      localStorage.setItem("agw.last-workspace", workspace.trim());
      onDone();
    } catch (caught) {
      setError(describeLoginError(caught));
    } finally {
      setBusy(false);
    }
  };

  const startGoogle = () => {
    localStorage.setItem("agw.last-workspace", workspace.trim());
    window.location.assign(googleLoginUrl(workspace.trim()));
  };

  const passwordEnabled = config?.password ?? true;
  const googleEnabled = config?.google ?? false;
  const noMethods = config !== null && !passwordEnabled && !googleEnabled;

  return (
    <div className="login">
      <div className="login__box">
        <div className="login__head">
          <div className="row" style={{ marginBottom: 16 }}>
            <span className="topbar__mark">AG</span>
            <strong style={{ fontSize: 14 }}>AI Gateway</strong>
          </div>
          <h1>Sign in</h1>
          <p>Control plane for agent identities, grants and tool calls.</p>
        </div>
        {expired ? (
          <div className="callout callout--error" style={{ margin: "0 24px 16px" }}>
            <div className="row" style={{ gap: 8 }}>
              <Icon name="alert" size={14} />
              Your session is no longer valid. Sign in again to load workspace data.
            </div>
          </div>
        ) : null}
        {ssoError ? (
          <div className="callout callout--error" style={{ margin: "0 24px 16px" }}>
            <div className="row" style={{ gap: 8 }}>
              <Icon name="alert" size={14} />
              {ssoError}
            </div>
          </div>
        ) : null}
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="workspace">Workspace</label>
            <input
              id="workspace"
              value={workspace}
              onChange={(event) => setWorkspace(event.target.value)}
              placeholder="acme"
              autoComplete="off"
              required
            />
          </div>
          {googleEnabled ? (
            <div className="field">
              <button
                className="btn"
                type="button"
                style={{ width: "100%" }}
                disabled={!workspace.trim()}
                onClick={startGoogle}
              >
                Continue with Google
              </button>
              <span className="field__hint">
                Google accounts from the domains allowed by the administrator.
              </span>
            </div>
          ) : null}
          {noMethods ? (
            <div className="callout callout--error">
              <div className="row" style={{ gap: 8 }}>
                <Icon name="alert" size={14} />
                Sign-in is not configured on this server. Contact an administrator.
              </div>
            </div>
          ) : null}
          {passwordEnabled ? (
            <>
              <div className="field">
                <label htmlFor="email">Work e-mail</label>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="owner@example.com"
                  autoComplete="username"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="password">Password</label>
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Your workspace password"
                  autoComplete="current-password"
                  minLength={8}
                  required
                />
              </div>
              {error ? (
                <div className="callout callout--error">
                  <div className="row" style={{ gap: 8 }}>
                    <Icon name="alert" size={14} />
                    {error}
                  </div>
                </div>
              ) : null}
              <button className="btn btn--primary" type="submit" disabled={busy}>
                {busy ? "Signing in…" : "Sign in"}
              </button>
            </>
          ) : null}
        </form>
        <div className="login__switch">
          <span>No account yet?</span>
          <button className="link-button" type="button" onClick={onSignup}>
            Request access
          </button>
        </div>
        <div className="login__note">
          Access requests are reviewed in Identities before a person or agent can sign in.
          {googleEnabled && passwordEnabled
            ? "Google sign-in and password sign-in both open the same session."
            : googleEnabled
              ? "Sign in with an allowed Google account."
              : "Sign in with the password set by a workspace administrator."}
        </div>
      </div>
    </div>
  );
}
