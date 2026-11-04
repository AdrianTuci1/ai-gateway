import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  ApiError,
  api,
  fmtDate,
  getWorkspace,
  type Agent,
  type Connection,
  type CredentialCreated,
  type Grant,
  type Inventory,
  type Service,
  type Tool,
} from "../api";
import { DataTable, type Column, type TableRow } from "../components/DataTable";
import { Shell } from "../components/Shell";
import { ErrorBox, Field, Modal, Skeleton, StatusBadge } from "../components/ui";
import { useAsync } from "../hooks";

export function ResourceDetail() {
  const { type, id } = useParams();
  if (!id) return null;
  if (type === "service") return <ServiceDetail id={id} />;
  if (type === "agent") return <AgentDetail id={id} />;
  return (
    <Shell title="Unknown resource" crumbs={[{ label: "All resources", to: "/resources" }]}>
      <div className="callout callout--error">
        Unknown resource type “{type}”. <Link to="/resources">Back to all resources</Link>.
      </div>
    </Shell>
  );
}

function useGroupName(groupId: string | null | undefined): { name: string | null; loading: boolean } {
  const ws = getWorkspace();
  const inventory = useAsync(
    () => api<Inventory>(`/v1/workspaces/${ws}/inventory`).catch(() => null),
    [ws],
  );
  const name = groupId
    ? (inventory.data?.groups.find((group) => group.id === groupId)?.name ?? null)
    : null;
  return { name, loading: inventory.loading };
}

function ServiceDetail({ id }: { id: string }) {
  const ws = getWorkspace();
  const navigate = useNavigate();
  const service = useAsync(() => api<Service>(`/v1/workspaces/${ws}/services/${id}`), [ws, id]);
  const tools = useAsync(
    () => api<Tool[]>(`/v1/workspaces/${ws}/services/${id}/tools`).catch(() => []),
    [ws, id],
  );
  const group = useGroupName(service.data?.resource_group_id);
  const [discovering, setDiscovering] = useState(false);
  const [discoverError, setDiscoverError] = useState<string | null>(null);

  const discover = async () => {
    setDiscovering(true);
    setDiscoverError(null);
    try {
      await api(`/v1/workspaces/${ws}/services/${id}/discover`, { method: "POST" });
      service.reload();
      tools.reload();
    } catch (error) {
      setDiscoverError(error instanceof ApiError ? error.message : "Discovery failed");
    } finally {
      setDiscovering(false);
    }
  };

  const data = service.data;
  const toolRows: TableRow<Tool>[] = (tools.data ?? []).map((tool) => ({
    key: tool.id,
    data: tool,
    nestedTitle: "Input schema",
    children: (
      <pre className="code-block">
        {JSON.stringify(tool.input_schema ?? {}, null, 2)}
      </pre>
    ),
  }));

  const columns: Column<Tool>[] = [
    { key: "name", header: "Tool", render: (tool) => <span className="mono">{tool.name}</span> },
    {
      key: "description",
      header: "Description",
      render: (tool) => <span className="muted">{tool.description ?? "—"}</span>,
    },
    { key: "seen", header: "Last seen", width: "180px", render: (tool) => <span className="nowrap">{fmtDate(tool.last_seen_at)}</span> },
    {
      key: "hash",
      header: "Definition hash",
      width: "180px",
      render: (tool) => <span className="mono muted">{tool.definition_hash.slice(0, 12)}…</span>,
    },
  ];

  return (
    <Shell
      title={data?.name ?? "Service"}
      suffix="Service"
      subtitle={data?.id ?? id}
      icon="server"
      crumbs={[
        { label: "Resource Manager" },
        { label: "All resources", to: "/resources" },
        { label: data?.name ?? "Service" },
      ]}
      commands={[
        {
          label: discovering ? "Discovering…" : "Discover tools",
          icon: "wand",
          primary: true,
          disabled: discovering,
          onClick: discover,
        },
        {
          label: "Edit",
          icon: "settings",
          onClick: () => navigate(`/resources/service/${id}/edit`),
        },
        { label: "Refresh", icon: "refresh", onClick: () => { service.reload(); tools.reload(); } },
      ]}
    >
      {service.error ? <ErrorBox error={service.error} onRetry={service.reload} /> : null}
      {discoverError ? <div className="callout callout--error">{discoverError}</div> : null}

      {service.loading ? (
        <Skeleton rows={5} />
      ) : data ? (
        <>
          <div className="grid grid--sidebar">
            <section className="panel">
              <div className="panel__header">
                <h2>Properties</h2>
                <div className="panel__actions">
                  <StatusBadge status={data.status} />
                </div>
              </div>
              <div className="panel__body">
                <dl className="kv">
                  <dt>Name</dt>
                  <dd>{data.name}</dd>
                  <dt>Kind</dt>
                  <dd>{data.kind}</dd>
                  <dt>Endpoint</dt>
                  <dd className="mono">{data.endpoint ?? "—"}</dd>
                  <dt>Authentication</dt>
                  <dd>{data.auth_type}</dd>
                  <dt>Credential policy</dt>
                  <dd>{data.credential_policy}</dd>
                  <dt>Resource group</dt>
                  <dd>
                    {data.resource_group_id ? (
                      <Link to={`/groups/${data.resource_group_id}`}>
                        {group.name ?? data.resource_group_id}
                      </Link>
                    ) : (
                      <span className="muted">Standalone</span>
                    )}
                  </dd>
                  <dt>Created</dt>
                  <dd>{fmtDate(data.created_at)}</dd>
                </dl>
              </div>
            </section>

            <section className="panel">
              <div className="panel__header">
                <h2>Manifest</h2>
              </div>
              <div className="panel__body">
                <dl className="kv">
                  <dt>Hash</dt>
                  <dd className="mono truncate">{data.manifest_hash ?? "Not discovered"}</dd>
                  <dt>Synced</dt>
                  <dd>{fmtDate(data.manifest_synced_at)}</dd>
                  <dt>Tools</dt>
                  <dd>{(tools.data ?? []).length}</dd>
                </dl>
                <div className="section-title">Runtime requirements</div>
                <pre className="code-block">
                  {JSON.stringify(data.runtime_requirements ?? {}, null, 2)}
                </pre>
              </div>
            </section>
          </div>

          <div className="section-title">
            Catalog
            <span className="muted small" style={{ fontWeight: 400 }}>
              Discovered tool definitions; expand a row for the input schema.
            </span>
          </div>
          {tools.loading ? (
            <Skeleton rows={4} />
          ) : (
            <DataTable
              columns={columns}
              rows={toolRows}
              empty="No tools in the catalog"
              emptyAction={
                <button className="btn btn--primary" type="button" onClick={discover} disabled={discovering}>
                  Run discovery
                </button>
              }
            />
          )}
        </>
      ) : null}
    </Shell>
  );
}

function AgentDetail({ id }: { id: string }) {
  const ws = getWorkspace();
  const navigate = useNavigate();
  const agent = useAsync(() => api<Agent>(`/v1/workspaces/${ws}/agents/${id}`), [ws, id]);
  const grants = useAsync(
    () => api<Grant[]>(`/v1/workspaces/${ws}/agents/${id}/grants`).catch(() => []),
    [ws, id],
  );
  const services = useAsync(
    () => api<Service[]>(`/v1/workspaces/${ws}/services`).catch(() => []),
    [ws],
  );
  const connections = useAsync(
    () => api<Connection[]>(`/v1/workspaces/${ws}/agents/${id}/connections`).catch(() => []),
    [ws, id],
  );
  const group = useGroupName(agent.data?.resource_group_id);
  const [credential, setCredential] = useState<CredentialCreated | null>(null);
  const [issuing, setIssuing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const serviceNames = new Map((services.data ?? []).map((service) => [service.id, service.name]));

  const issueKey = async () => {
    setIssuing(true);
    setActionError(null);
    try {
      setCredential(
        await api<CredentialCreated>(`/v1/workspaces/${ws}/agents/${id}/credentials`, {
          method: "POST",
        }),
      );
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : "Could not issue a credential");
    } finally {
      setIssuing(false);
    }
  };

  const revoke = async (grant: Grant) => {
    const name = serviceNames.get(grant.service_id) ?? grant.service_id;
    if (!window.confirm(`Revoke this agent's grant on “${name}”? Calls will be denied immediately.`)) {
      return;
    }
    setActionError(null);
    try {
      await api(`/v1/workspaces/${ws}/agents/${id}/grants/${grant.service_id}`, {
        method: "DELETE",
      });
      grants.reload();
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : "Could not revoke the grant");
    }
  };

  const data = agent.data;
  const grantColumns: Column<Grant>[] = [
    {
      key: "service",
      header: "Service",
      render: (grant) => (
        <Link to={`/resources/service/${grant.service_id}`}>
          {serviceNames.get(grant.service_id) ?? grant.service_id}
        </Link>
      ),
    },
    {
      key: "tools",
      header: "Tools",
      render: (grant) => (
        <span className="tag-list">
          {grant.tools.map((tool) => (
            <span className="tag" key={tool}>
              {tool}
            </span>
          ))}
        </span>
      ),
    },
    {
      key: "constraints",
      header: "Constraints",
      width: "130px",
      render: (grant) =>
        Object.keys(grant.arg_constraints ?? {}).length > 0 ? (
          <span className="muted">argument rules</span>
        ) : (
          <span className="muted">—</span>
        ),
    },
    { key: "status", header: "Status", width: "110px", render: (grant) => <StatusBadge status={grant.status} /> },
    {
      key: "expires",
      header: "Expires",
      width: "180px",
      render: (grant) => (
        <span className="nowrap">{grant.expires_at ? fmtDate(grant.expires_at) : "never"}</span>
      ),
    },
    {
      key: "actions",
      header: "",
      width: "170px",
      render: (grant) => (
        <span className="row" style={{ gap: 4 }}>
          <Link className="btn btn--small" to={`/resources/agent/${id}/grants/${grant.service_id}`}>
            Edit
          </Link>
          <button
            className="btn btn--small"
            type="button"
            onClick={() => revoke(grant)}
            disabled={grant.status !== "active"}
          >
            Revoke
          </button>
        </span>
      ),
    },
  ];

  const grantRows: TableRow<Grant>[] = (grants.data ?? []).map((grant) => ({
    key: grant.id,
    data: grant,
    nestedTitle: "Argument constraints",
    children: (
      <pre className="code-block">
        {JSON.stringify(grant.arg_constraints ?? {}, null, 2)}
      </pre>
    ),
  }));

  return (
    <Shell
      title={data?.name ?? "Agent"}
      suffix="Agent"
      subtitle={data ? `${data.slug} · ${data.id}` : id}
      icon="agent"
      crumbs={[
        { label: "Resource Manager" },
        { label: "All resources", to: "/resources" },
        { label: data?.name ?? "Agent" },
      ]}
      commands={[
        {
          label: issuing ? "Issuing…" : "Issue API key",
          icon: "key",
          primary: true,
          disabled: issuing,
          onClick: issueKey,
        },
        {
          label: "New grant",
          icon: "shield",
          onClick: () => navigate(`/resources/agent/${id}/grants/new`),
        },
        { label: "Edit", icon: "settings", onClick: () => navigate(`/resources/agent/${id}/edit`) },
        { label: "Refresh", icon: "refresh", onClick: () => { agent.reload(); grants.reload(); } },
      ]}
    >
      {agent.error ? <ErrorBox error={agent.error} onRetry={agent.reload} /> : null}
      {actionError ? <div className="callout callout--error">{actionError}</div> : null}

      {agent.loading ? (
        <Skeleton rows={5} />
      ) : data ? (
        <>
          <div className="grid grid--sidebar">
            <section className="panel">
              <div className="panel__header">
                <h2>Properties</h2>
                <div className="panel__actions">
                  <StatusBadge status={data.status} />
                </div>
              </div>
              <div className="panel__body">
                <dl className="kv">
                  <dt>Name</dt>
                  <dd>{data.name}</dd>
                  <dt>Slug</dt>
                  <dd className="mono">{data.slug}</dd>
                  <dt>Kind</dt>
                  <dd>{data.kind}</dd>
                  <dt>Resource group</dt>
                  <dd>
                    {data.resource_group_id ? (
                      <Link to={`/groups/${data.resource_group_id}`}>
                        {group.name ?? data.resource_group_id}
                      </Link>
                    ) : (
                      <span className="muted">Standalone</span>
                    )}
                  </dd>
                  <dt>Created</dt>
                  <dd>{fmtDate(data.created_at)}</dd>
                  <dt>Grants</dt>
                  <dd>{(grants.data ?? []).length}</dd>
                  <dt>Connections</dt>
                  <dd>{(connections.data ?? []).length}</dd>
                </dl>
              </div>
            </section>

            <section className="panel">
              <div className="panel__header">
                <h2>Ceiling</h2>
              </div>
              <div className="panel__body">
                <p className="muted small" style={{ marginTop: 0 }}>
                  Hard limit on what this agent may ever be granted. Grants are capped by this
                  ceiling; each call is then checked against the grant itself.
                </p>
                <pre className="code-block">{JSON.stringify(data.ceiling ?? {}, null, 2)}</pre>
              </div>
            </section>
          </div>

          <div className="section-title">
            Grants
            <span className="muted small" style={{ fontWeight: 400 }}>
              Calls are denied unless a matching tool grant exists.
            </span>
          </div>
          {grants.loading ? (
            <Skeleton rows={4} />
          ) : (
            <DataTable
              columns={grantColumns}
              rows={grantRows}
              empty="No grants"
              emptyAction={
                <Link className="btn btn--primary" to={`/resources/agent/${id}/grants/new`}>
                  New grant
                </Link>
              }
            />
          )}

          {(connections.data ?? []).length > 0 ? (
            <>
              <div className="section-title">User connections</div>
              <div className="table-wrap">
                <table className="grid-table">
                  <thead>
                    <tr>
                      <th>Service</th>
                      <th style={{ width: 140 }}>Binding</th>
                      <th style={{ width: 120 }}>Status</th>
                      <th style={{ width: 220 }}>Scopes</th>
                      <th style={{ width: 180 }}>Expires</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(connections.data ?? []).map((connection) => (
                      <tr key={connection.id}>
                        <td>
                          <Link to={`/resources/service/${connection.service_id}`}>
                            {serviceNames.get(connection.service_id) ?? connection.service_id}
                          </Link>
                        </td>
                        <td>{connection.binding}</td>
                        <td>
                          <StatusBadge status={connection.status} />
                        </td>
                        <td>
                          <span className="tag-list">
                            {connection.scopes.map((scope) => (
                              <span className="tag" key={scope}>
                                {scope}
                              </span>
                            ))}
                          </span>
                        </td>
                        <td>
                          <span className="nowrap">
                            {connection.expires_at ? fmtDate(connection.expires_at) : "never"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
        </>
      ) : null}

      {credential ? (
        <Modal
          title="New API key"
          onClose={() => setCredential(null)}
          footer={
            <button className="btn btn--primary" type="button" onClick={() => setCredential(null)}>
              Done
            </button>
          }
        >
          <p className="muted small" style={{ margin: 0 }}>
            Copy this key now. The gateway stores only its hash, so it cannot be shown again.
          </p>
          <Field label="Credential">
            <input readOnly value={credential.api_key ?? ""} className="mono" />
          </Field>
          <Field label="Prefix">
            <input readOnly value={credential.prefix ?? ""} className="mono" />
          </Field>
          <Field label="Expires">
            <input readOnly value={credential.expires_at ?? "never"} />
          </Field>
          <button
            className="btn"
            type="button"
            onClick={() => {
              if (credential.api_key) void navigator.clipboard?.writeText(credential.api_key);
            }}
          >
            Copy key to clipboard
          </button>
        </Modal>
      ) : null}
    </Shell>
  );
}
