import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  ApiError,
  api,
  fmtDate,
  getWorkspace,
  type Grant,
  type Inventory,
  type ResourceItem,
  type Service,
  type Tool,
} from "../api";
import { DataTable, type Column, type TableRow } from "../components/DataTable";
import { Shell } from "../components/Shell";
import { ErrorBox, Skeleton, StatusBadge } from "../components/ui";
import { useAsync } from "../hooks";
import { useState } from "react";

export function Resources() {
  const ws = getWorkspace();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const inventory = useAsync(() => api<Inventory>(`/v1/workspaces/${ws}/inventory`), [ws]);
  const services = useAsync(
    () => api<Service[]>(`/v1/workspaces/${ws}/services`).catch(() => []),
    [ws],
  );

  const type = params.get("type") ?? "all";
  const group = params.get("group") ?? "all";
  const query = params.get("q") ?? "";

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (!value || value === "all") next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  };

  const serviceNames = new Map((services.data ?? []).map((service) => [service.id, service.name]));
  const groups = inventory.data?.groups ?? [];
  const all: ResourceItem[] = [
    ...groups.flatMap((item) => item.resources),
    ...(inventory.data?.standalone ?? []),
  ];
  const groupNames = new Map(groups.map((item) => [item.id, item.name]));

  const rowsData = all
    .filter((resource) => type === "all" || resource.type === type)
    .filter((resource) =>
      group === "all"
        ? true
        : group === "standalone"
          ? resource.group_id === null
          : resource.group_id === group,
    )
    .filter((resource) => resource.name.toLowerCase().includes(query.toLowerCase()))
    .sort((left, right) =>
      left.name.localeCompare(right.name) || left.type.localeCompare(right.type),
    );

  const columns: Column<ResourceItem>[] = [
    {
      key: "name",
      header: "Name",
      render: (resource) => (
        <span className="cell-name">
          <Link to={`/resources/${resource.type}/${resource.id}`}>{resource.name}</Link>
        </span>
      ),
    },
    {
      key: "type",
      header: "Type",
      width: "110px",
      render: (resource) => <span className="muted">{resource.type}</span>,
    },
    { key: "kind", header: "Kind", width: "140px", render: (resource) => resource.kind },
    {
      key: "group",
      header: "Resource group",
      width: "190px",
      render: (resource) =>
        resource.group_id ? (
          <Link to={`/groups/${resource.group_id}`}>{groupNames.get(resource.group_id) ?? "group"}</Link>
        ) : (
          <span className="muted">Standalone</span>
        ),
    },
    {
      key: "detail",
      header: "Endpoint / slug",
      truncate: true,
      render: (resource) => <span className="mono muted truncate">{resource.detail ?? "—"}</span>,
    },
    {
      key: "status",
      header: "Status",
      width: "120px",
      render: (resource) => <StatusBadge status={resource.status} />,
    },
    {
      key: "children",
      header: "Children",
      width: "100px",
      align: "right",
      render: (resource) => resource.children,
    },
  ];

  const rows: TableRow<ResourceItem>[] = rowsData.map((resource) => ({
    key: `${resource.type}-${resource.id}`,
    data: resource,
    nestedTitle: resource.type === "service" ? "Tools in catalog" : "Granted services",
    children: <ResourceChildren resource={resource} serviceNames={serviceNames} />,
  }));

  return (
    <Shell
      title="AI Gateway"
      suffix="All resources"
      subtitle={`${ws} · ${all.length} resources across ${groups.length} groups`}
      icon="grid"
      crumbs={[{ label: "Resource Manager" }, { label: "All resources" }]}
      commands={[
        {
          label: "Create service",
          icon: "plus",
          primary: true,
          onClick: () => navigate("/resources/new?type=service"),
        },
        {
          label: "Create agent",
          icon: "agent",
          onClick: () => navigate("/resources/new?type=agent"),
        },
        {
          label: "Create resource group",
          icon: "layers",
          onClick: () => navigate("/groups/new"),
        },
        { label: "Refresh", icon: "refresh", onClick: () => { inventory.reload(); services.reload(); } },
        {
          label: "Export to CSV",
          icon: "download",
          disabled: rowsData.length === 0,
          onClick: () => exportCsv(rowsData, groupNames),
        },
      ]}
    >
      {inventory.error ? <ErrorBox error={inventory.error} onRetry={inventory.reload} /> : null}

      <div className="filters">
        <div className="topbar__search" style={{ maxWidth: 320 }}>
          <span aria-hidden="true">⌕</span>
          <input
            aria-label="Filter resources"
            placeholder="Filter by name"
            value={query}
            onChange={(event) => setParam("q", event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="resource-type">Type</label>
          <select
            id="resource-type"
            value={type}
            onChange={(event) => setParam("type", event.target.value)}
          >
            <option value="all">All types</option>
            <option value="service">Services</option>
            <option value="agent">Agents</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="resource-group">Group</label>
          <select
            id="resource-group"
            value={group}
            onChange={(event) => setParam("group", event.target.value)}
          >
            <option value="all">All groups</option>
            <option value="standalone">Standalone</option>
            {groups.map((item) => (
              <option value={item.id} key={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
        <span className="muted small" style={{ marginLeft: "auto" }}>
          {rowsData.length} of {all.length} resources
        </span>
      </div>

      {inventory.loading ? (
        <Skeleton rows={7} />
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          empty="No resources match this filter"
          emptyAction={
            <span className="row">
              <Link className="btn btn--primary" to="/resources/new?type=service">
                Create service
              </Link>
              <Link className="btn" to="/resources/new?type=agent">
                Create agent
              </Link>
            </span>
          }
        />
      )}
    </Shell>
  );
}

function ResourceChildren({
  resource,
  serviceNames,
}: {
  resource: ResourceItem;
  serviceNames: Map<string, string>;
}) {
  return resource.type === "service" ? (
    <ServiceTools serviceId={resource.id} />
  ) : (
    <AgentGrants agentId={resource.id} serviceNames={serviceNames} />
  );
}

function ServiceTools({ serviceId }: { serviceId: string }) {
  const ws = getWorkspace();
  const tools = useAsync(
    () => api<Tool[]>(`/v1/workspaces/${ws}/services/${serviceId}/tools`),
    [ws, serviceId],
  );
  const [discovering, setDiscovering] = useState(false);
  const [discoverError, setDiscoverError] = useState<string | null>(null);

  const discover = async () => {
    setDiscovering(true);
    setDiscoverError(null);
    try {
      await api(`/v1/workspaces/${ws}/services/${serviceId}/discover`, { method: "POST" });
      tools.reload();
    } catch (error) {
      setDiscoverError(error instanceof ApiError ? error.message : "Discovery failed");
    } finally {
      setDiscovering(false);
    }
  };

  if (tools.loading) return <Skeleton rows={3} />;
  if (tools.error) return <ErrorBox error={tools.error} onRetry={tools.reload} />;
  if ((tools.data ?? []).length === 0) {
    return (
      <div className="row row--between">
        <span className="muted small">
          No tools discovered yet. Run discovery to fill the catalog from the upstream.
        </span>
        {discoverError ? <span className="callout callout--error">{discoverError}</span> : null}
        <button className="btn btn--small" type="button" onClick={discover} disabled={discovering}>
          {discovering ? "Discovering…" : "Discover tools"}
        </button>
      </div>
    );
  }

  return (
    <table className="grid-table">
      <thead>
        <tr>
          <th>Tool</th>
          <th>Description</th>
          <th style={{ width: 190 }}>Last seen</th>
          <th style={{ width: 220 }}>Definition hash</th>
        </tr>
      </thead>
      <tbody>
        {(tools.data ?? []).map((tool) => (
          <tr key={tool.id}>
            <td className="mono">{tool.name}</td>
            <td className="muted">{tool.description ?? "—"}</td>
            <td>
              <span className="nowrap">{fmtDate(tool.last_seen_at)}</span>
            </td>
            <td className="mono muted truncate">{tool.definition_hash.slice(0, 16)}…</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AgentGrants({
  agentId,
  serviceNames,
}: {
  agentId: string;
  serviceNames: Map<string, string>;
}) {
  const ws = getWorkspace();
  const grants = useAsync(
    () => api<Grant[]>(`/v1/workspaces/${ws}/agents/${agentId}/grants`),
    [ws, agentId],
  );

  if (grants.loading) return <Skeleton rows={3} />;
  if (grants.error) return <ErrorBox error={grants.error} onRetry={grants.reload} />;
  if ((grants.data ?? []).length === 0) {
    return <div className="muted small">This agent has no grants. Calls are denied by default.</div>;
  }

  return (
    <table className="grid-table">
      <thead>
        <tr>
          <th>Service</th>
          <th>Tools</th>
          <th style={{ width: 110 }}>Status</th>
          <th style={{ width: 180 }}>Expires</th>
          <th style={{ width: 180 }}>Updated</th>
        </tr>
      </thead>
      <tbody>
        {(grants.data ?? []).map((grant) => (
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

function exportCsv(resources: ResourceItem[], groupNames: Map<string, string>) {
  const header = "name,type,kind,resource_group,status,children,detail\n";
  const body = resources
    .map((resource) =>
      [
        resource.name,
        resource.type,
        resource.kind,
        resource.group_id ? (groupNames.get(resource.group_id) ?? resource.group_id) : "standalone",
        resource.status,
        resource.children,
        resource.detail ?? "",
      ]
        .map((value) => `"${String(value).replace(/"/g, '""')}"`)
        .join(","),
    )
    .join("\n");
  download("resources.csv", header + body);
}

function download(name: string, content: string) {
  const blob = new Blob([content], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}
