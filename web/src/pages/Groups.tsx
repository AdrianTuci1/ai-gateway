import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, fmtDate, getWorkspace, type Inventory, type ResourceGroup } from "../api";
import { DataTable, type Column, type TableRow } from "../components/DataTable";
import { Shell } from "../components/Shell";
import { ErrorBox, Skeleton, StatusBadge } from "../components/ui";
import { useAsync } from "../hooks";

export function Groups() {
  const ws = getWorkspace();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const inventory = useAsync(() => api<Inventory>(`/v1/workspaces/${ws}/inventory`), [ws]);

  const groups = (inventory.data?.groups ?? []).filter((group) =>
    group.name.toLowerCase().includes(query.toLowerCase()),
  );

  const columns: Column<ResourceGroup>[] = [
    {
      key: "name",
      header: "Name",
      render: (group) => (
        <span className="cell-name">
          <Link to={`/groups/${group.id}`}>{group.name}</Link>
        </span>
      ),
    },
    { key: "kind", header: "Kind", width: "150px", render: (group) => group.kind },
    {
      key: "count",
      header: "Resources",
      width: "110px",
      align: "right",
      render: (group) => group.resources.length,
    },
    {
      key: "services",
      header: "Services",
      width: "100px",
      align: "right",
      render: (group) => group.resources.filter((resource) => resource.type === "service").length,
    },
    {
      key: "agents",
      header: "Agents",
      width: "100px",
      align: "right",
      render: (group) => group.resources.filter((resource) => resource.type === "agent").length,
    },
    {
      key: "id",
      header: "Group ID",
      width: "280px",
      truncate: true,
      render: (group) => (
        <span className="mono muted" title={group.id}>
          {group.id}
        </span>
      ),
    },
    {
      key: "created",
      header: "Created",
      width: "190px",
      render: (group) => <span className="nowrap">{fmtDate(group.created_at)}</span>,
    },
  ];

  const rows: TableRow<ResourceGroup>[] = groups.map((group) => ({
    key: group.id,
    data: group,
    nestedTitle: "Resources",
    children: <ResourceTable group={group} />,
  }));

  return (
    <Shell
      title="Resource Manager"
      suffix="Resource groups"
      subtitle={`${ws} · ${groups.length} groups`}
      icon="layers"
      crumbs={[{ label: "Resource Manager" }, { label: "Resource groups" }]}
      commands={[
        { label: "Create", icon: "plus", primary: true, onClick: () => navigate("/groups/new") },
        { label: "Refresh", icon: "refresh", onClick: inventory.reload },
        {
          label: "Export to CSV",
          icon: "download",
          disabled: groups.length === 0,
          onClick: () => exportCsv(groups),
        },
      ]}
    >
      {inventory.error ? <ErrorBox error={inventory.error} onRetry={inventory.reload} /> : null}

      <div className="row" style={{ marginBottom: 12 }}>
        <div className="topbar__search" style={{ maxWidth: 360 }}>
          <span aria-hidden="true">⌕</span>
          <input
            aria-label="Search groups"
            placeholder="Search by name"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <span className="muted small">Resource groups collect services and agents; membership is navigation, not a policy boundary.</span>
      </div>

      {inventory.loading ? (
        <Skeleton rows={6} />
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          empty="No resource groups"
          emptyAction={
            <Link className="btn btn--primary" to="/groups/new">
              Create resource group
            </Link>
          }
        />
      )}

    </Shell>
  );
}

function ResourceTable({ group }: { group: ResourceGroup }) {
  if (group.resources.length === 0) {
    return <div className="muted small">This group has no resources. Open the group to add some.</div>;
  }
  return (
    <table className="grid-table">
      <thead>
        <tr>
          <th>Name</th>
          <th style={{ width: 110 }}>Type</th>
          <th style={{ width: 140 }}>Kind</th>
          <th style={{ width: 120 }}>Status</th>
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
  );
}

function exportCsv(groups: ResourceGroup[]) {
  const header = "name,kind,resources,services,agents,id,created\n";
  const body = groups
    .map((group) =>
      [
        group.name,
        group.kind,
        group.resources.length,
        group.resources.filter((resource) => resource.type === "service").length,
        group.resources.filter((resource) => resource.type === "agent").length,
        group.id,
        group.created_at,
      ].join(","),
    )
    .join("\n");
  const blob = new Blob([header + body], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "resource-groups.csv";
  link.click();
  URL.revokeObjectURL(url);
}
