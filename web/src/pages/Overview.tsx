import { Link, useNavigate } from "react-router-dom";

import {
  api,
  fmtDuration,
  getWorkspace,
  type IdentityGroup,
  type Inventory,
  type TraceSummary,
} from "../api";
import { DataTable, type Column, type TableRow } from "../components/DataTable";
import { Icon } from "../components/Icon";
import { Shell } from "../components/Shell";
import { ErrorBox, Skeleton, StatusBadge } from "../components/ui";
import { useAsync } from "../hooks";

export function Overview() {
  const ws = getWorkspace();
  const navigate = useNavigate();
  const inventory = useAsync(() => api<Inventory>(`/v1/workspaces/${ws}/inventory`), [ws]);
  const identities = useAsync(
    () =>
      api<IdentityGroup[]>(`/v1/workspaces/${ws}/identity-groups`).catch(() => []),
    [ws],
  );
  const traces = useAsync(
    () => api<TraceSummary[]>(`/v1/workspaces/${ws}/traces?limit=8`).catch(() => []),
    [ws],
  );

  const counts = inventory.data?.counts;
  const groups = inventory.data?.groups ?? [];
  const standalone = inventory.data?.standalone ?? [];

  const columns: Column<Inventory["groups"][number]>[] = [
    {
      key: "name",
      header: "Name",
      render: (group) => (
        <span className="cell-name">
          <Link to={`/groups/${group.id}`}>{group.name}</Link>
        </span>
      ),
    },
    { key: "kind", header: "Kind", width: "140px", render: (group) => group.kind },
    {
      key: "count",
      header: "Resources",
      width: "110px",
      align: "right",
      render: (group) => group.resources.length,
    },
  ];

  const rows: TableRow<Inventory["groups"][number]>[] = groups.map((group) => ({
    key: group.id,
    data: group,
    nestedTitle: "Resources in this group",
    children: (
      <table className="grid-table">
        <thead>
          <tr>
            <th>Name</th>
            <th style={{ width: 120 }}>Type</th>
            <th style={{ width: 140 }}>Kind</th>
            <th style={{ width: 110 }}>Status</th>
            <th style={{ width: 90 }} className="cell-num">
              Children
            </th>
          </tr>
        </thead>
        <tbody>
          {group.resources.map((resource) => (
            <tr key={`${resource.type}-${resource.id}`}>
              <td>
                <Link to={`/resources/${resource.type}/${resource.id}`}>{resource.name}</Link>
              </td>
              <td>{resource.type}</td>
              <td>{resource.kind}</td>
              <td>
                <StatusBadge status={resource.status} />
              </td>
              <td className="cell-num">{resource.children}</td>
            </tr>
          ))}
        </tbody>
      </table>
    ),
  }));

  return (
    <Shell
      title="AI Gateway"
      suffix="Overview"
      subtitle={`${ws} · control plane for agent identity, policy and catalog`}
      icon="home"
      commands={[
        { label: "Create resource group", icon: "plus", primary: true, onClick: () => navigate("/groups/new") },
        { label: "All resources", icon: "grid", onClick: () => navigate("/resources") },
        { label: "Refresh", icon: "refresh", onClick: () => { inventory.reload(); traces.reload(); identities.reload(); } },
      ]}
    >
      {inventory.error ? <ErrorBox error={inventory.error} onRetry={inventory.reload} /> : null}

      <div className="grid grid--3">
        <IntroCard
          title="Register a resource"
          text="Connect an HTTP API, an MCP server or another agent. Discovery fills the tool catalog, and every call is filtered by grants."
          action="Open resources"
          icon="server"
          to="/resources"
        />
        <IntroCard
          title="Organize with groups"
          text="Group resources the way your teams own them. Resources can also stand alone; navigation follows the same hierarchy either way."
          action="Manage groups"
          icon="layers"
          to="/groups"
        />
        <IntroCard
          title="Review identities"
          text="An umbrella identity groups one person and their agents under one approval. Each entity keeps its own role, permissions and granted resources."
          action="See identities"
          icon="users"
          to="/identities"
        />
      </div>

      <div className="stat-row" style={{ marginTop: 16 }}>
        <Stat label="Resource groups" value={counts?.groups} loading={inventory.loading} />
        <Stat label="Services" value={counts?.services} loading={inventory.loading} />
        <Stat label="Agents" value={counts?.agents} loading={inventory.loading} />
        <Stat label="Identity groups" value={identities.data?.length} loading={identities.loading} />
      </div>

      <div className="grid grid--sidebar" style={{ marginTop: 16 }}>
        <section>
          <div className="section-title">
            Resource groups
            <span className="muted small" style={{ fontWeight: 400 }}>
              {groups.length} groups · {standalone.length} standalone resources
            </span>
            <Link to="/groups" className="small" style={{ marginLeft: "auto", fontWeight: 400 }}>
              View all
            </Link>
          </div>
          {inventory.loading ? (
            <Skeleton rows={4} />
          ) : (
            <DataTable columns={columns} rows={rows} empty="No resource groups yet." />
          )}
        </section>

        <section>
          <div className="section-title">
            Recent traces
            <Link to="/tracing" className="small" style={{ marginLeft: "auto", fontWeight: 400 }}>
              Open tracing
            </Link>
          </div>
          <div className="table-wrap">
            <table className="grid-table">
              <thead>
                <tr>
                  <th>Operation</th>
                  <th style={{ width: 90 }} className="cell-num">
                    Duration
                  </th>
                  <th style={{ width: 90 }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {(traces.data ?? []).map((trace) => (
                  <tr key={trace.trace_id}>
                    <td>
                      <div className="truncate" style={{ maxWidth: 170 }} title={trace.root_name}>
                        <Link to={`/tracing/${trace.trace_id}`} className="mono">
                          {trace.root_name}
                        </Link>
                      </div>
                    </td>
                    <td className="cell-num mono">{fmtDuration(trace.duration_ms)}</td>
                    <td>
                      <StatusBadge status={trace.status} />
                    </td>
                  </tr>
                ))}
                {(traces.data ?? []).length === 0 ? (
                  <tr>
                    <td colSpan={3} className="muted">
                      No requests recorded yet. Call the API to see traces here.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          <div className="callout" style={{ marginTop: 12 }}>
            <div className="row" style={{ gap: 8 }}>
              <Icon name="trace" size={14} />
              <span>
                Every API request writes a root span; each MCP tool call adds a child span. Open a
                trace to see the waterfall.
              </span>
            </div>
          </div>
        </section>
      </div>
    </Shell>
  );
}

function IntroCard({
  title,
  text,
  action,
  icon,
  to,
}: {
  title: string;
  text: string;
  action: string;
  icon: string;
  to: string;
}) {
  return (
    <article className="intro-card">
      <div className="intro-card__art">
        <Icon name={icon} size={44} />
      </div>
      <div className="intro-card__body">
        <h3>{title}</h3>
        <p>{text}</p>
        <div>
          <Link className="btn btn--primary" to={to}>
            {action}
          </Link>
        </div>
      </div>
    </article>
  );
}

function Stat({
  label,
  value,
  loading,
}: {
  label: string;
  value: number | undefined;
  loading: boolean;
}) {
  return (
    <div className="stat">
      <div className="stat__value">{loading ? "—" : (value ?? 0)}</div>
      <div className="stat__label">{label}</div>
    </div>
  );
}
