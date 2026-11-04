import { useState } from "react";
import { Link } from "react-router-dom";

import {
  api,
  fmtDate,
  getWorkspace,
  type Agent,
  type Grant,
  type Service,
} from "../api";
import { DataTable, type Column, type TableRow } from "../components/DataTable";
import { Shell } from "../components/Shell";
import { ErrorBox, Skeleton, StatusBadge } from "../components/ui";
import { useAsync } from "../hooks";

type AgentPolicies = { agent: Agent; grants: Grant[] };

export function Grants() {
  const ws = getWorkspace();
  const [query, setQuery] = useState("");

  const policies = useAsync<{ agents: AgentPolicies[]; services: Service[] }>(async () => {
    const [agents, services] = await Promise.all([
      api<Agent[]>(`/v1/workspaces/${ws}/agents`),
      api<Service[]>(`/v1/workspaces/${ws}/services`).catch(() => []),
    ]);
    const grants = await Promise.all(
      agents.map((agent) =>
        api<Grant[]>(`/v1/workspaces/${ws}/agents/${agent.id}/grants`).catch(() => []),
      ),
    );
    return {
      agents: agents.map((agent, index) => ({ agent, grants: grants[index] ?? [] })),
      services,
    };
  }, [ws]);

  const serviceNames = new Map(
    (policies.data?.services ?? []).map((service) => [service.id, service.name]),
  );
  const agents = policies.data?.agents ?? [];
  const withGrants = agents.filter((entry) => entry.grants.length > 0);
  const allGrants = agents.flatMap((entry) => entry.grants);

  const visible = agents.filter((entry) => {
    const haystack = [
      entry.agent.name,
      entry.agent.slug,
      ...entry.grants.map((grant) => serviceNames.get(grant.service_id) ?? ""),
      ...entry.grants.flatMap((grant) => grant.tools),
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(query.toLowerCase());
  });

  const columns: Column<AgentPolicies>[] = [
    {
      key: "agent",
      header: "Agent",
      render: (entry) => (
        <span className="cell-name">
          <Link to={`/resources/agent/${entry.agent.id}`}>{entry.agent.name}</Link>
        </span>
      ),
    },
    {
      key: "slug",
      header: "Slug",
      width: "200px",
      render: (entry) => <span className="mono muted">{entry.agent.slug}</span>,
    },
    {
      key: "kind",
      header: "Kind",
      width: "130px",
      render: (entry) => entry.agent.kind,
    },
    {
      key: "status",
      header: "Status",
      width: "120px",
      render: (entry) => <StatusBadge status={entry.agent.status} />,
    },
    {
      key: "services",
      header: "Services",
      width: "100px",
      align: "right",
      render: (entry) => entry.grants.length,
    },
    {
      key: "tools",
      header: "Tools",
      width: "90px",
      align: "right",
      render: (entry) =>
        entry.grants.reduce((total, grant) => total + grant.tools.length, 0),
    },
    {
      key: "updated",
      header: "Last change",
      width: "190px",
      render: (entry) => {
        const latest = entry.grants
          .map((grant) => grant.updated_at)
          .sort()
          .at(-1);
        return latest ? fmtDate(latest) : <span className="muted">—</span>;
      },
    },
  ];

  const rows: TableRow<AgentPolicies>[] = visible.map((entry) => ({
    key: entry.agent.id,
    data: entry,
    nestedTitle: "Service grants",
    children: <GrantTable grants={entry.grants} serviceNames={serviceNames} />,
  }));

  return (
    <Shell
      title="AI Gateway"
      suffix="Policies & grants"
      subtitle={`${ws} · ${allGrants.length} grants on ${withGrants.length} agents`}
      icon="shield"
      crumbs={[{ label: "Access control" }, { label: "Policies & grants" }]}
      commands={[
        { label: "Refresh", icon: "refresh", primary: true, onClick: policies.reload },
        { label: "Identities", icon: "users", onClick: () => { window.location.assign("/identities"); } },
      ]}
    >
      {policies.error ? <ErrorBox error={policies.error} onRetry={policies.reload} /> : null}

      <div className="callout" style={{ marginBottom: 12 }}>
        Access is deny-by-default: an agent may call a tool only when an active grant covers it.
        Each agent's ceiling caps what any grant can contain, so tightening the ceiling also
        bounds existing grants.
      </div>

      <div className="filters">
        <div className="topbar__search" style={{ maxWidth: 360 }}>
          <span aria-hidden="true">⌕</span>
          <input
            aria-label="Filter grants"
            placeholder="Filter by agent, service or tool"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <span className="muted small" style={{ marginLeft: "auto" }}>
          {visible.length} of {agents.length} agents · {allGrants.length} grants
        </span>
      </div>

      {policies.loading ? (
        <Skeleton rows={6} />
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          empty="No agents in this workspace"
          emptyAction={
            <Link className="btn" to="/resources?type=agent">
              Browse agents
            </Link>
          }
        />
      )}
    </Shell>
  );
}

function GrantTable({
  grants,
  serviceNames,
}: {
  grants: Grant[];
  serviceNames: Map<string, string>;
}) {
  if (grants.length === 0) {
    return <div className="muted small">No grants. Every call from this agent is denied.</div>;
  }
  return (
    <table className="grid-table">
      <thead>
        <tr>
          <th>Service</th>
          <th>Tools</th>
          <th style={{ width: 110 }}>Status</th>
          <th style={{ width: 170 }}>Expires</th>
          <th style={{ width: 170 }}>Updated</th>
        </tr>
      </thead>
      <tbody>
        {grants.map((grant) => (
          <tr key={grant.id}>
            <td>
              <Link to={`/resources/service/${grant.service_id}`}>
                {serviceNames.get(grant.service_id) ?? grant.service_id}
              </Link>
            </td>
            <td>
              <span className="tag-list">
                {grant.tools.map((tool) => (
                  <span className="tag" key={tool}>
                    {tool}
                  </span>
                ))}
              </span>
            </td>
            <td>
              <StatusBadge status={grant.status} />
            </td>
            <td>
              <span className="nowrap">{grant.expires_at ? fmtDate(grant.expires_at) : "never"}</span>
            </td>
            <td>
              <span className="nowrap">{fmtDate(grant.updated_at)}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
