import { useState } from "react";
import { Link } from "react-router-dom";

import {
  ApiError,
  api,
  fmtDate,
  getWorkspace,
  type IdentityEntity,
  type IdentityGroup,
  type IdentityInviteCreated,
  type Me,
  type SignupRequest,
} from "../api";
import { DataTable, type Column, type TableRow } from "../components/DataTable";
import { Shell } from "../components/Shell";
import {
  Badge,
  ErrorBox,
  Modal,
  Skeleton,
  StatusBadge,
} from "../components/ui";
import { useAsync } from "../hooks";

const HUMAN_ROLES = ["viewer", "developer", "operator", "admin", "owner"];

export function Identities() {
  const ws = getWorkspace();
  const groups = useAsync(
    () => api<IdentityGroup[]>(`/v1/workspaces/${ws}/identity-groups`),
    [ws],
  );
  const signups = useAsync(
    () => api<SignupRequest[]>(`/v1/workspaces/${ws}/signups?status=pending`),
    [ws],
  );
  const me = useAsync(() => api<Me>("/v1/me"), [ws]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"all" | "active" | "pending" | "rejected">("all");
  const [inviting, setInviting] = useState<IdentityGroup | null>(null);

  const reload = () => {
    groups.reload();
    signups.reload();
    me.reload();
  };

  const workspaceAdmin = (me.data?.permissions ?? []).includes("identity:approve");
  const pending = signups.data ?? [];
  const all = groups.data ?? [];

  const pendingColumns: Column<SignupRequest>[] = [
    {
      key: "requester",
      header: "Requester",
      render: (request) => (
        <span className="cell-name">
          {request.kind === "user"
            ? request.display_name ?? request.email
            : request.agent_name ?? request.agent_slug}
        </span>
      ),
    },
    {
      key: "identity",
      header: "Identity",
      render: (request) => (
        <span>
          {request.identity_name ?? "—"}
          {request.owner_email ? (
            <span className="muted small"> · {request.owner_email}</span>
          ) : null}
        </span>
      ),
    },
    {
      key: "kind",
      header: "Kind",
      width: "100px",
      render: (request) => (
        <Badge tone={request.kind === "user" ? "info" : "plain"}>{request.kind}</Badge>
      ),
    },
    {
      key: "detail",
      header: "E-mail / slug",
      render: (request) => (
        <span className="mono">{request.email ?? request.agent_slug ?? "—"}</span>
      ),
    },
    {
      key: "role",
      header: "Requested role",
      width: "180px",
      render: (request) => (
        <span className="mono">{request.requested_role ?? "—"}</span>
      ),
    },
    {
      key: "created",
      header: "Submitted",
      width: "180px",
      render: (request) => <span className="nowrap">{fmtDate(request.created_at)}</span>,
    },
    {
      key: "action",
      header: "",
      width: "100px",
      align: "right",
      render: (request) => (
        <Link className="btn btn--small" to={`/identities/requests/${request.id}`}>
          Review
        </Link>
      ),
    },
  ];

  const pendingRows: TableRow<SignupRequest>[] = pending.map((request) => ({
    key: request.id,
    data: request,
  }));

  const rowsData = all
    .filter((group) => status === "all" || group.status === status)
    .filter((group) => {
      const haystack = [
        group.name,
        group.owner_email ?? "",
        ...group.entities.flatMap((entity) => [
          entity.name,
          entity.email ?? "",
          entity.role,
        ]),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(query.toLowerCase());
    });

  const columns: Column<IdentityGroup>[] = [
    {
      key: "name",
      header: "Identity",
      render: (group) => (
        <span className="cell-name">
          {group.name}
          {group.entities.some((entity) => entity.is_identity_admin) ? (
            <Badge tone="info">admin</Badge>
          ) : null}
        </span>
      ),
    },
    {
      key: "entities",
      header: "Entities",
      width: "120px",
      render: (group) => {
        const people = group.entities.filter((entity) => entity.kind === "user").length;
        const agents = group.entities.filter((entity) => entity.kind === "agent").length;
        return (
          <span className="muted">
            {people} {people === 1 ? "person" : "people"} · {agents}{" "}
            {agents === 1 ? "agent" : "agents"}
          </span>
        );
      },
    },
    {
      key: "owner",
      header: "Owner e-mail",
      render: (group) => (
        <span className={group.owner_email ? "mono" : "muted"}>
          {group.owner_email ?? "—"}
        </span>
      ),
    },
    {
      key: "signup",
      header: "Signup",
      width: "130px",
      render: (group) =>
        group.signup_id ? (
          <Link className="mono small" to={`/identities/requests/${group.signup_id}`}>
            {group.requested_role ?? "request"}
          </Link>
        ) : (
          <span className="muted">—</span>
        ),
    },
    {
      key: "status",
      header: "Status",
      width: "120px",
      render: (group) => <StatusBadge status={group.status} />,
    },
    {
      key: "created",
      header: "Created",
      width: "180px",
      render: (group) => <span className="nowrap">{fmtDate(group.created_at)}</span>,
    },
    {
      key: "action",
      header: "",
      width: "120px",
      align: "right",
      render: (group) =>
        group.can_manage && group.status === "active" ? (
          <button
            className="btn btn--small"
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              setInviting(group);
            }}
          >
            Invite
          </button>
        ) : null,
    },
  ];

  const rows: TableRow<IdentityGroup>[] = rowsData.map((group) => ({
    key: group.id,
    data: group,
    nestedTitle: "Entities",
    children: <GroupDetail group={group} />,
  }));

  const entityCount = all.reduce((total, group) => total + group.entities.length, 0);

  return (
    <Shell
      title="AI Gateway"
      suffix="Identities"
      subtitle={`${ws} · ${all.length} identities · ${entityCount} entities${
        pending.length ? ` · ${pending.length} pending` : ""
      }`}
      icon="users"
      crumbs={[{ label: "Access control" }, { label: "Identities" }]}
      commands={[
        {
          label: "Manage grants",
          icon: "shield",
          primary: true,
          onClick: () => {
            window.location.assign("/grants");
          },
        },
        { label: "Refresh", icon: "refresh", onClick: reload },
      ]}
    >
      {groups.error ? <ErrorBox error={groups.error} onRetry={reload} /> : null}
      {signups.error ? <ErrorBox error={signups.error} onRetry={reload} /> : null}
      {me.error ? <ErrorBox error={me.error} onRetry={reload} /> : null}

      <div className="callout" style={{ marginBottom: 12 }}>
        An identity is the umbrella for one person and their agents. Approval activates the
        whole group, and the approved agent can become its administrator. That administrator
        can invite the person into the same identity without another workspace approval.
      </div>

      {pending.length ? (
        <>
          <div className="section-title">
            Pending access requests
            <Badge tone="warn">{pending.length}</Badge>
            <span className="muted small" style={{ fontWeight: 400 }}>
              Review a request to choose its role and approve or reject it.
            </span>
          </div>
          <DataTable
            columns={pendingColumns}
            rows={pendingRows}
            empty="No pending access requests"
          />
        </>
      ) : (
        <div className="muted small" style={{ marginBottom: 12 }}>
          No pending access requests.
        </div>
      )}

      <div className="section-title">Identity groups</div>

      <div className="filters">
        <div className="topbar__search" style={{ maxWidth: 320 }}>
          <span aria-hidden="true">⌕</span>
          <input
            aria-label="Filter identities"
            placeholder="Filter by identity, person, agent or role"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="identity-status">Status</label>
          <select
            id="identity-status"
            value={status}
            onChange={(event) =>
              setStatus(event.target.value as "all" | "active" | "pending" | "rejected")
            }
          >
            <option value="all">All statuses</option>
            <option value="active">Active</option>
            <option value="pending">Pending</option>
            <option value="rejected">Rejected</option>
          </select>
        </div>
        <span className="muted small" style={{ marginLeft: "auto" }}>
          {rowsData.length} of {all.length}
        </span>
      </div>

      {groups.loading ? (
        <Skeleton rows={6} />
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          empty="No identities in this workspace"
          emptyAction={
            <span className="muted small">
              Bootstrap the workspace to create the owner identity.
            </span>
          }
        />
      )}

      {inviting ? (
        <InviteModal
          group={inviting}
          workspaceAdmin={workspaceAdmin}
          onClose={() => setInviting(null)}
          onDone={reload}
        />
      ) : null}
    </Shell>
  );
}

function GroupDetail({ group }: { group: IdentityGroup }) {
  if (group.entities.length === 0) {
    return (
      <div className="muted small">
        No memberships yet. {group.status === "pending" ? "Approval activates the group." : ""}
      </div>
    );
  }
  return (
    <div className="stack">
      <div className="nested">
        <table className="grid-table">
          <thead>
            <tr>
              <th scope="col">Entity</th>
              <th scope="col">Kind</th>
              <th scope="col">Role</th>
              <th scope="col">Grants</th>
              <th scope="col">Status</th>
              <th scope="col">Last seen</th>
            </tr>
          </thead>
          <tbody>
            {group.entities.map((entity) => (
              <tr key={`${entity.kind}-${entity.id}`}>
                <td>
                  <span className="cell-name">
                    {entity.kind === "agent" ? (
                      <Link to={`/resources/agent/${entity.id}`}>{entity.name}</Link>
                    ) : (
                      <>
                        {entity.name}
                        {entity.email ? (
                          <span className="muted small"> · {entity.email}</span>
                        ) : null}
                      </>
                    )}
                    {entity.is_identity_admin ? (
                      <Badge tone="info">identity admin</Badge>
                    ) : null}
                  </span>
                </td>
                <td>
                  <Badge tone={entity.kind === "user" ? "info" : "plain"}>
                    {entity.kind}
                  </Badge>
                </td>
                <td className="mono">{entity.role}</td>
                <td className="cell-num">{entity.grant_count}</td>
                <td>
                  <StatusBadge status={entity.status} />
                </td>
                <td className="nowrap">{fmtDate(entity.last_seen_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {group.decision_note ? (
        <div className="muted small">Decision note: {group.decision_note}</div>
      ) : null}
      <EntityPermissions entities={group.entities} />
    </div>
  );
}

function EntityPermissions({ entities }: { entities: IdentityEntity[] }) {
  const roles = new Map<string, string[]>();
  for (const entity of entities) {
    if (!roles.has(entity.role)) roles.set(entity.role, entity.permissions);
  }
  return (
    <div className="stack">
      {[...roles.entries()].map(([role, permissions]) => (
        <div className="row" style={{ flexWrap: "wrap" }} key={role}>
          <span className="muted small" style={{ minWidth: 96 }}>
            {role}
          </span>
          {permissions.length === 0 ? (
            <span className="muted small">This role has no permissions.</span>
          ) : (
            <span className="tag-list">
              {permissions.map((permission) => (
                <span className="tag" key={permission}>
                  {permission}
                </span>
              ))}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function InviteModal({
  group,
  workspaceAdmin,
  onClose,
  onDone,
}: {
  group: IdentityGroup;
  workspaceAdmin: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const ws = getWorkspace();
  const defaultEmail =
    group.owner_email ??
    group.entities.find((entity) => entity.kind === "user")?.email ??
    "";
  const [email, setEmail] = useState(defaultEmail);
  const [role, setRole] = useState("viewer");
  const [created, setCreated] = useState<IdentityInviteCreated | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const options = workspaceAdmin ? HUMAN_ROLES : ["viewer"];

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api<IdentityInviteCreated>(
        `/v1/workspaces/${ws}/identity-groups/${group.id}/invites`,
        {
          method: "POST",
          body: JSON.stringify({ email: email.trim(), role }),
        },
      );
      setCreated(result);
      onDone();
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "The invite could not be created.",
      );
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.invite_url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Copy failed. Select the link and copy it manually.");
    }
  };

  return (
    <Modal
      title={`Invite into ${group.name}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn" type="button" onClick={onClose}>
            Close
          </button>
          {created ? (
            <button className="btn btn--primary" type="button" onClick={copy}>
              {copied ? "Copied" : "Copy link"}
            </button>
          ) : (
            <button
              className="btn btn--primary"
              type="submit"
              form="invite-form"
              disabled={busy}
            >
              {busy ? "Creating…" : "Create link"}
            </button>
          )}
        </>
      }
    >
      {error ? <div className="callout callout--error">{error}</div> : null}
      {created ? (
        <div className="stack">
          <p className="muted small" style={{ margin: 0 }}>
            Send this one-time link to {created.email}. They create their account and join{" "}
            <strong>{created.identity_name}</strong> without another approval.
          </p>
          <code className="code-inline" style={{ wordBreak: "break-all" }}>
            {created.invite_url}
          </code>
          <div className="muted small">
            Role: <span className="mono">{created.role}</span> · Expires{" "}
            {fmtDate(created.expires_at)}
          </div>
          <a className="btn btn--small" href={created.invite_url} target="_blank" rel="noreferrer">
            Open claim page
          </a>
        </div>
      ) : (
        <form id="invite-form" className="stack" onSubmit={create}>
          <div className="field">
            <label htmlFor="invite-email">Person's e-mail</label>
            <input
              id="invite-email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="dana@example.com"
              required
            />
            <span className="field__hint">
              The link is tied to this address and can be used once.
            </span>
          </div>
          <div className="field">
            <label htmlFor="invite-role">Role</label>
            <select
              id="invite-role"
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
              {workspaceAdmin
                ? "Workspace admins can grant any human role."
                : "Identity administrators invite people as viewers."}
            </span>
          </div>
        </form>
      )}
    </Modal>
  );
}
