import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  ApiError,
  api,
  fmtDate,
  getWorkspace,
  type SignupDecision,
  type SignupRequest,
} from "../api";
import { Shell } from "../components/Shell";
import {
  ErrorBox,
  Skeleton,
  StatusBadge,
} from "../components/ui";
import { useAsync } from "../hooks";

const HUMAN_ROLES = ["viewer", "developer", "operator", "admin", "owner"];
const AGENT_ROLES = [
  "agent:executor",
  "agent:requester",
  "agent:editor",
  "agent:admin",
];

function defaultRole(request: SignupRequest): string {
  const options = request.kind === "user" ? HUMAN_ROLES : AGENT_ROLES;
  const requested = request.requested_role;
  if (requested && options.includes(requested)) return requested;
  return request.kind === "user" ? "viewer" : "agent:executor";
}

export function SignupReview() {
  const { id } = useParams();
  const ws = getWorkspace();
  const navigate = useNavigate();
  const request = useAsync(
    () => api<SignupRequest>(`/v1/workspaces/${ws}/signups/${id}`),
    [ws, id],
  );
  const [role, setRole] = useState("");
  const [note, setNote] = useState("");
  const [decision, setDecision] = useState<SignupDecision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const data = decision?.request ?? request.data;
    if (!data) return;
    setRole((current) => current || defaultRole(data));
  }, [decision, request.data]);

  const decide = async (action: "approve" | "reject") => {
    if (!id) return;
    setBusy(action);
    setError(null);
    try {
      const result = await api<SignupDecision>(
        `/v1/workspaces/${ws}/signups/${id}/${action}`,
        {
          method: "POST",
          body: JSON.stringify({ role, note: note.trim() || undefined }),
        },
      );
      setDecision(result);
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "The decision could not be saved.",
      );
    } finally {
      setBusy(null);
    }
  };

  const copy = async () => {
    const key = decision?.credential?.api_key;
    if (!key) return;
    try {
      await navigator.clipboard.writeText(key);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Copy failed. Select the key and copy it manually.");
    }
  };

  const data = decision?.request ?? request.data;
  const roles = data?.kind === "agent" ? AGENT_ROLES : HUMAN_ROLES;
  const options =
    data?.requested_role && !roles.includes(data.requested_role)
      ? [data.requested_role, ...roles]
      : roles;

  return (
    <Shell
      title="AI Gateway"
      suffix="Access request"
      subtitle={data ? `${data.kind} · ${data.email ?? data.agent_slug ?? data.id}` : ws}
      icon="users"
      crumbs={[
        { label: "Access control" },
        { label: "Identities", to: "/identities" },
        { label: "Request" },
      ]}
      commands={[
        { label: "Back to identities", icon: "arrowLeft", onClick: () => navigate("/identities") },
        { label: "Refresh", icon: "refresh", onClick: request.reload },
      ]}
    >
      {request.error ? (
        <ErrorBox error={request.error} onRetry={request.reload} />
      ) : null}
      {error ? <div className="callout callout--error">{error}</div> : null}

      {request.loading && !decision ? (
        <Skeleton rows={6} />
      ) : data ? (
        <div className="grid grid--sidebar">
          <section className="panel">
            <div className="panel__header">
              <h2>Request</h2>
              <div className="panel__actions">
                <StatusBadge status={data.status} />
              </div>
            </div>
            <div className="panel__body">
              <dl className="kv">
                <dt>Kind</dt>
                <dd>{data.kind}</dd>
                <dt>Name</dt>
                <dd>
                  {data.kind === "user"
                    ? data.display_name ?? "—"
                    : data.agent_name ?? "—"}
                </dd>
                {data.kind === "user" ? (
                  <>
                    <dt>E-mail</dt>
                    <dd>{data.email ?? "—"}</dd>
                  </>
                ) : (
                  <>
                    <dt>Agent slug</dt>
                    <dd className="mono">{data.agent_slug ?? "—"}</dd>
                  </>
                )}
                <dt>Identity</dt>
                <dd>{data.identity_name ?? "—"}</dd>
                {data.kind === "agent" && data.owner_email ? (
                  <>
                    <dt>Owner e-mail</dt>
                    <dd className="mono">{data.owner_email}</dd>
                  </>
                ) : null}
                <dt>Requested role</dt>
                <dd className="mono">{data.requested_role ?? "—"}</dd>
                <dt>Submitted</dt>
                <dd>{fmtDate(data.created_at)}</dd>
                <dt>Request id</dt>
                <dd className="mono">{data.id}</dd>
              </dl>
              {data.message ? (
                <>
                  <div className="section-title">Message</div>
                  <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{data.message}</p>
                </>
              ) : null}
            </div>
          </section>

          <section className="panel">
            <div className="panel__header">
              <h2>{data.status === "pending" ? "Decision" : "Outcome"}</h2>
            </div>
            <div className="panel__body">
              {data.status === "pending" ? (
                <div className="stack">
                  <div className="field">
                    <label htmlFor="signup-role">
                      {data.kind === "user" ? "Human role" : "Agent role"}
                    </label>
                    <select
                      id="signup-role"
                      value={role}
                      onChange={(event) => setRole(event.target.value)}
                    >
                      {options.map((entry) => (
                        <option key={entry} value={entry}>
                          {entry}
                        </option>
                      ))}
                    </select>
                    <span className="field__hint">
                      The approver chooses the role; the request cannot grant it.
                    </span>
                  </div>
                  <div className="field">
                    <label htmlFor="signup-note">Decision note</label>
                    <textarea
                      id="signup-note"
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                      placeholder="Optional. Recorded in the audit log."
                      maxLength={1000}
                    />
                  </div>
                  <div className="row" style={{ gap: 8 }}>
                    <button
                      className="btn btn--primary"
                      type="button"
                      disabled={busy !== null}
                      onClick={() => decide("approve")}
                    >
                      {busy === "approve" ? "Approving…" : "Approve"}
                    </button>
                    <button
                      className="btn"
                      type="button"
                      disabled={busy !== null}
                      onClick={() => decide("reject")}
                    >
                      {busy === "reject" ? "Rejecting…" : "Reject"}
                    </button>
                  </div>
                  {data.kind === "agent" ? (
                    <p className="muted small" style={{ margin: 0 }}>
                      Approval creates the agent, makes it administrator of{" "}
                      {data.identity_name ?? "its identity"} and returns an API key once. The
                      agent can then invite {data.owner_email ?? "the person"} into the same
                      identity without another approval.
                    </p>
                  ) : (
                    <p className="muted small" style={{ margin: 0 }}>
                      Approval activates the membership immediately; the person can sign in
                      with this e-mail.
                    </p>
                  )}
                </div>
              ) : (
                <div className="stack">
                  <div className="row" style={{ gap: 8 }}>
                    <StatusBadge status={data.status} />
                    <span className="muted small">{fmtDate(data.decided_at)}</span>
                  </div>
                  {data.status === "approved" ? (
                    <div className="callout callout--success">
                      {data.kind === "user"
                        ? "The person can sign in now."
                        : "The agent is active and holds a new API key."}
                    </div>
                  ) : (
                    <div className="callout callout--error">
                      The request was rejected. The identity cannot sign in.
                    </div>
                  )}
                  {data.decision_note ? (
                    <div>
                      <div className="muted small">Decision note</div>
                      <p style={{ margin: "4px 0 0", whiteSpace: "pre-wrap" }}>
                        {data.decision_note}
                      </p>
                    </div>
                  ) : null}

                  {decision?.credential?.api_key ? (
                    <div className="stack">
                      <div className="muted small">
                        API key — shown once, copy it now. Expires{" "}
                        {fmtDate(decision.credential.expires_at)}
                      </div>
                      <div className="row" style={{ gap: 8 }}>
                        <code className="code-inline" style={{ flex: 1 }}>
                          {decision.credential.api_key}
                        </code>
                        <button className="btn btn--small" type="button" onClick={copy}>
                          {copied ? "Copied" : "Copy"}
                        </button>
                      </div>
                      {decision.request.principal_id ? (
                        <Link
                          className="btn btn--small"
                          to={`/resources/agent/${decision.request.principal_id}`}
                        >
                          Open agent
                        </Link>
                      ) : null}
                      <Link className="btn btn--small" to="/identities">
                        Invite the identity owner
                      </Link>
                    </div>
                  ) : null}

                  <Link className="btn" to="/identities">
                    Back to identities
                  </Link>
                </div>
              )}
            </div>
          </section>
        </div>
      ) : null}
    </Shell>
  );
}
