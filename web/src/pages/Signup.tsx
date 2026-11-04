import { useState } from "react";

import {
  ApiError,
  requestSignup,
  type SignupCreate,
  type SignupRequest,
} from "../api";
import { Icon } from "../components/Icon";
import { StatusBadge } from "../components/ui";

export function Signup({ onBack }: { onBack: () => void }) {
  const [workspace, setWorkspace] = useState(
    localStorage.getItem("agw.last-workspace") ?? "",
  );
  const [kind, setKind] = useState<"user" | "agent">("user");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [agentName, setAgentName] = useState("");
  const [agentSlug, setAgentSlug] = useState("");
  const [identityName, setIdentityName] = useState("");
  const [ownerEmail, setOwnerEmail] = useState("");
  const [message, setMessage] = useState("");
  const [submitted, setSubmitted] = useState<SignupRequest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const body: SignupCreate = {
      kind,
      identity_name: identityName.trim() || undefined,
      message: message.trim() || undefined,
    };
    if (kind === "user") {
      body.email = email.trim();
      body.display_name = name.trim() || undefined;
      body.password = password;
    } else {
      body.agent_name = agentName.trim() || agentSlug.trim();
      body.agent_slug = agentSlug.trim();
      body.owner_email = ownerEmail.trim() || undefined;
    }
    try {
      const result = await requestSignup(workspace.trim(), body);
      localStorage.setItem("agw.last-workspace", workspace.trim());
      setSubmitted(result);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "The request could not be submitted. Check that the gateway is reachable.",
      );
    } finally {
      setBusy(false);
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
          <h1>{submitted ? "Request received" : "Request access"}</h1>
          <p>
            {submitted
              ? "An owner or admin reviews the identity before it becomes usable."
              : "Request a person or agent identity in a workspace. An owner or admin approves the umbrella identity."}
          </p>
        </div>

        {submitted ? (
          <>
            <div className="login__body">
              <div className="callout callout--success">
                <div className="row row--between">
                  <span>
                    Request <span className="mono">{submitted.id.slice(0, 8)}</span> for{" "}
                    <strong>
                      {submitted.kind === "user"
                        ? submitted.email
                        : submitted.agent_slug}
                    </strong>{" "}
                    is queued.
                  </span>
                  <StatusBadge status={submitted.status} />
                </div>
              </div>
              <p className="muted small" style={{ margin: 0 }}>
                A workspace owner or admin approves it from Identities. Until then, sign-in
                stays closed for this identity.
              </p>
              <button className="btn btn--primary" type="button" onClick={onBack}>
                Back to sign in
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={submit}>
            <div className="field">
              <label htmlFor="signup-workspace">Workspace</label>
              <input
                id="signup-workspace"
                value={workspace}
                onChange={(event) => setWorkspace(event.target.value)}
                placeholder="acme"
                autoComplete="off"
                required
              />
            </div>
            <div className="field">
              <label htmlFor="signup-kind">Account type</label>
              <select
                id="signup-kind"
                value={kind}
                onChange={(event) => setKind(event.target.value as "user" | "agent")}
              >
                <option value="user">Person</option>
                <option value="agent">Agent</option>
              </select>
            </div>

            {kind === "user" ? (
              <>
                <div className="field">
                  <label htmlFor="signup-name">Full name</label>
                  <input
                    id="signup-name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="Dana Popescu"
                    autoComplete="name"
                  />
                </div>
                <div className="field">
                  <label htmlFor="signup-email">Work e-mail</label>
                  <input
                    id="signup-email"
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="dana@example.com"
                    autoComplete="email"
                    required
                  />
                </div>
                <div className="field">
                  <label htmlFor="signup-password">Password</label>
                  <input
                    id="signup-password"
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder="At least 8 characters"
                    autoComplete="new-password"
                    minLength={8}
                    required
                  />
                  <span className="field__hint">
                    You will use this password after an admin approves the identity.
                  </span>
                </div>
              </>
            ) : (
              <>
                <div className="field">
                  <label htmlFor="signup-agent-name">Agent name</label>
                  <input
                    id="signup-agent-name"
                    value={agentName}
                    onChange={(event) => setAgentName(event.target.value)}
                    placeholder="Research Bot"
                    autoComplete="off"
                  />
                </div>
                <div className="field">
                  <label htmlFor="signup-agent-slug">Agent slug</label>
                  <input
                    id="signup-agent-slug"
                    value={agentSlug}
                    onChange={(event) => setAgentSlug(event.target.value)}
                    placeholder="research-bot"
                    pattern="[a-z0-9][a-z0-9\-]*"
                    minLength={2}
                    maxLength={80}
                    autoComplete="off"
                    required
                  />
                  <span className="field__hint">
                    Lowercase letters, digits and dashes. The slug is the identity key.
                  </span>
                </div>
                <div className="field">
                  <label htmlFor="signup-owner-email">Person's e-mail (optional)</label>
                  <input
                    id="signup-owner-email"
                    type="email"
                    value={ownerEmail}
                    onChange={(event) => setOwnerEmail(event.target.value)}
                    placeholder="dana@example.com"
                    autoComplete="email"
                  />
                  <span className="field__hint">
                    If this person has no account yet, the approved agent can invite them
                    into the same identity.
                  </span>
                </div>
              </>
            )}

            <div className="field">
              <label htmlFor="signup-identity">Identity name</label>
              <input
                id="signup-identity"
                value={identityName}
                onChange={(event) => setIdentityName(event.target.value)}
                placeholder={kind === "user" ? "Dana Popescu" : "Dana"}
                autoComplete="off"
              />
              <span className="field__hint">
                People and agents that share an identity share one approval. Leave blank to
                use the name above.
              </span>
            </div>

            <div className="field">
              <label htmlFor="signup-message">Why do you need access?</label>
              <textarea
                id="signup-message"
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                placeholder="Optional context for the approver."
                maxLength={1000}
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
              {busy ? "Submitting…" : "Submit request"}
            </button>
          </form>
        )}

        <div className="login__switch">
          <span>Already have an account?</span>
          <button className="link-button" type="button" onClick={onBack}>
            Sign in
          </button>
        </div>
        <div className="login__note">
          Roles are chosen by the approver. A self-service request never grants access on its
          own. An approved agent becomes administrator of its identity and can invite the
          person it belongs to.
        </div>
      </div>
    </div>
  );
}
