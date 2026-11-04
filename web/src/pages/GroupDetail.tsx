import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, fmtDate, getWorkspace, type Inventory } from "../api";
import { DataTable, type Column, type TableRow } from "../components/DataTable";
import { Shell } from "../components/Shell";
import { ErrorBox, Skeleton, StatusBadge } from "../components/ui";
import { useAsync } from "../hooks";

export function GroupDetail() {
  const { id } = useParams();
  const ws = getWorkspace();
  const navigate = useNavigate();
  const [tab, setTab] = useState<"overview" | "resources">("overview");
  const inventory = useAsync(() => api<Inventory>(`/v1/workspaces/${ws}/inventory`), [ws]);

  const group = inventory.data?.groups.find((entry) => entry.id === id) ?? null;

  if (inventory.loading) {
    return (
      <Shell title="Resource group" crumbs={[{ label: "Resource groups", to: "/groups" }]}>
        <Skeleton rows={5} />
      </Shell>
    );
  }

  if (!group) {
    return (
      <Shell title="Resource group" crumbs={[{ label: "Resource groups", to: "/groups" }]}>
        <div className="callout">
          This resource group does not exist in the workspace.{" "}
          <Link to="/groups">Back to resource groups</Link>.
        </div>
      </Shell>
    );
  }

  const remove = async () => {
    if (!window.confirm(`Delete resource group “${group.name}”? Its resources become standalone.`)) {
      return;
    }
    await api(`/v1/workspaces/${ws}/resource-groups/${group.id}`, { method: "DELETE" });
    navigate("/groups");
  };

  const columns: Column<{ type: string; id: string; name: string; kind: string; status: string; children: number }>[] = [
    {
      key: "name",
      header: "Name",
      render: (resource) => (
        <span className="cell-name">
          <Link to={`/resources/${resource.type}/${resource.id}`}>{resource.name}</Link>
        </span>
      ),
    },
    { key: "type", header: "Type", width: "110px", render: (resource) => resource.type },
    { key: "kind", header: "Kind", width: "150px", render: (resource) => resource.kind },
    { key: "status", header: "Status", width: "130px", render: (resource) => <StatusBadge status={resource.status} /> },
    { key: "children", header: "Children", width: "100px", align: "right", render: (resource) => resource.children },
  ];

  const rows: TableRow<(typeof group.resources)[number]>[] = group.resources.map((resource) => ({
    key: `${resource.type}-${resource.id}`,
    data: resource,
  }));

  return (
    <Shell
      title={group.name}
      suffix="Resource group"
      subtitle={group.id}
      icon="layers"
      crumbs={[{ label: "Resource Manager" }, { label: "Resource groups", to: "/groups" }, { label: group.name }]}
      commands={[
        { label: "Add resources", icon: "plus", primary: true, onClick: () => navigate(`/groups/${group.id}/resources`) },
        { label: tab === "overview" ? "Resources" : "Overview", icon: "chevron", onClick: () => setTab(tab === "overview" ? "resources" : "overview") },
        { label: "Edit", icon: "settings", onClick: () => navigate(`/groups/${group.id}/edit`) },
        { label: "Delete", icon: "close", onClick: remove },
      ]}
      tabs={[
        { label: "Overview", to: "#overview", onClick: () => setTab("overview") },
        {
          label: "Resources",
          to: "#resources",
          count: group.resources.length,
          onClick: () => setTab("resources"),
        },
      ]}
      activeTab={tab === "overview" ? "#overview" : "#resources"}
    >
      <div className="command-bar" style={{ margin: "0 -24px 16px", paddingLeft: 24 }}>
        <span className="muted small">
          {group.kind} · created {fmtDate(group.created_at)}
        </span>
      </div>

      {tab === "overview" ? (
        <div className="grid grid--sidebar">
          <section className="panel">
            <div className="panel__header">
              <h2>Properties</h2>
            </div>
            <div className="panel__body">
              <dl className="kv">
                <dt>Name</dt>
                <dd>{group.name}</dd>
                <dt>Group ID</dt>
                <dd className="mono">{group.id}</dd>
                <dt>Kind</dt>
                <dd>{group.kind}</dd>
                <dt>Description</dt>
                <dd>{group.description || <span className="muted">No description</span>}</dd>
                <dt>Resources</dt>
                <dd>{group.resources.length}</dd>
                <dt>Services</dt>
                <dd>{group.resources.filter((resource) => resource.type === "service").length}</dd>
                <dt>Agents</dt>
                <dd>{group.resources.filter((resource) => resource.type === "agent").length}</dd>
                <dt>Created</dt>
                <dd>{fmtDate(group.created_at)}</dd>
              </dl>
            </div>
          </section>
          <section className="panel">
            <div className="panel__header">
              <h2>Members</h2>
            </div>
            <div className="panel__body stack">
              {group.resources.length === 0 ? (
                <span className="muted small">No resources yet.</span>
              ) : (
                group.resources.map((resource) => (
                  <div key={resource.id} className="row row--between">
                    <span>
                      <span className={`badge badge--plain`} style={{ marginRight: 8 }}>
                        {resource.type}
                      </span>
                      <Link to={`/resources/${resource.type}/${resource.id}`}>{resource.name}</Link>
                    </span>
                    <StatusBadge status={resource.status} />
                  </div>
                ))
              )}
              <Link className="btn btn--small" to={`/groups/${group.id}/resources`} style={{ alignSelf: "flex-start" }}>
                Manage resources
              </Link>
            </div>
          </section>
        </div>
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          empty="No resources in this group"
          emptyAction={
            <Link className="btn btn--primary" to={`/groups/${group.id}/resources`}>
              Add resources
            </Link>
          }
        />
      )}

      {inventory.error ? <ErrorBox error={inventory.error} onRetry={inventory.reload} /> : null}

    </Shell>
  );
}
