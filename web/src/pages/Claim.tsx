import { useState } from "react";
import { useParams } from "react-router-dom";

import {
  ApiError,
  api,
  fmtDate,
  setSession,
  type IdentityInviteAccepted,
  type IdentityInvitePreview,
} from "../api";
import { Icon } from "../components/Icon";
import { StatusBadge } from "../components/ui";
import { useAsync } from "../hooks";

export function Claim() {
  const { token } = useParams();
  const preview = useAsync(
    () => api<IdentityInvitePreview>(`/v1/identity-invites/${token}`),
    [token],
  );
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [accepted, setAccepted] = useState<IdentityInviteAccepted | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const accept = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api<IdentityInviteAccepted>(
        `/v1/identity-invites/${token}/accept`,
        {
          method: "POST",
          body: JSON.stringify({
            display_name: name.trim() || undefined,
            password,
          }),
        },
      );
      setSession(
        result.token,
        result.workspace_slug,
        result.user.email,
      );
      setAccepted(result);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "The invitation could not be accepted.",
      );
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!accepted) return;
    try {
      await navigator.clipboard.writeText(accepted.token);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Copy failed. Select the token and copy it manually.");
    }
  };

  return (
    <div className="login">
      <div className="login__box login__box--wide">
        <div className="login__head">
          <div className="row" style={{ marginBottom: 16 }}>
            <span className="topbar__mark">AG</span>
            <strong style={{ fontSize: 14 }}>AI Gateway</strong>
          </div>
          <h1>{accepted ? "Account ready" : "Join your identity"}</h1>
          <p>
            {accepted
              ? `You are now a member of ${accepted.identity_name}.`
              : "An identity administrator invited you. Accepting creates your account and adds you to the same identity as the agent."}
          </p>
        </div>

        {preview.error ? (
          <div className="login__body">
            <div className="callout callout--error">
              <div className="row" style={{ gap: 8 }}>
                <Icon name="alert" size={14} />
                This invitation is invalid, expired or already used.
              </div>
            </div>
            <button
              className="btn"
              type="button"
              onClick={() => window.location.assign("/")}
            >
              Go to sign in
            </button>
          </div>
        ) : accepted ? (
          <div className="login__body">
            <div className="callout callout--success">
              <div className="row row--between">
                <span>
                  <strong>{accepted.user.email}</strong> joined{" "}
                  <strong>{accepted.identity_name}</strong> in{" "}
                  {accepted.workspace_slug}.
                </span>
                <StatusBadge status="active" />
              </div>
            </div>
            <p className="muted small" style={{ margin: 0 }}>
              The browser holds a session for this workspace. You can enter the console now.
            </p>
            <div className="stack">
              <code className="code-inline" style={{ wordBreak: "break-all" }}>
                {accepted.token}
              </code>
              <div className="row" style={{ gap: 8 }}>
                <button className="btn" type="button" onClick={copy}>
                  {copied ? "Copied" : "Copy session token"}
                </button>
                <button
                  className="btn btn--primary"
                  type="button"
                  onClick={() => window.location.assign("/")}
                >
                  Enter console
                </button>
              </div>
            </div>
          </div>
        ) : preview.loading ? (
          <div className="login__body">
            <span className="muted small">Checking the invitation…</span>
          </div>
        ) : preview.data ? (
          <form onSubmit={accept}>
            <div className="login__body">
              <dl className="kv">
                <dt>Workspace</dt>
                <dd>{preview.data.workspace_name}</dd>
                <dt>Identity</dt>
                <dd>{preview.data.identity_name}</dd>
                <dt>E-mail</dt>
                <dd className="mono">{preview.data.email}</dd>
                <dt>Role</dt>
                <dd className="mono">{preview.data.role}</dd>
                <dt>Expires</dt>
                <dd>{fmtDate(preview.data.expires_at)}</dd>
              </dl>
              <div className="field">
                <label htmlFor="claim-name">Your name</label>
                <input
                  id="claim-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Dana Popescu"
                  autoComplete="name"
                />
                <span className="field__hint">
                  Optional. The account uses the invited e-mail address.
                </span>
              </div>

              <div className="field">
                <label htmlFor="claim-password">Password</label>
                <input
                  id="claim-password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="At least 8 characters"
                  autoComplete="new-password"
                  minLength={8}
                  required
                />
                <span className="field__hint">
                  Use this password together with your e-mail at the next sign-in.
                </span>
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
                {busy ? "Joining…" : `Join ${preview.data.identity_name}`}
              </button>
            </div>
          </form>
        ) : null}

        <div className="login__note">
          One-time link. The token stops working after the account is created.
        </div>
      </div>
    </div>
  );
}
