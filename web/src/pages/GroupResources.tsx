import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, api, getWorkspace, type Inventory, type ResourceGroup } from "../api";
import { Shell } from "../components/Shell";
import { ErrorBox, Skeleton, StatusBadge } from "../components/ui";
import { useAsync } from "../hooks";

export function GroupResources() {
  const { id } = useParams();
  const ws = getWorkspace();
  const navigate = useNavigate();
  const inventory = useAsync(() => api<Inventory>(`/v1/workspaces/${ws}/inventory`), [ws]);
  const group = inventory.data?.groups.find((entry) => entry.id === id) ?? null;
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!group) return;
    setSelected(new Set(group.resources.map((resource) => `${resource.type}-${resource.id}`)));
  }, [group]);

  const all = Array.from(
    new Map(
      [
        ...(inventory.data?.groups.flatMap((entry) => entry.resources) ?? []),
        ...(inventory.data?.standalone ?? []),
      ].map((resource) => [`${resource.type}-${resource.id}`, resource]),
    ).values(),
  ).sort((left, right) => left.name.localeCompare(right.name));

  const toggle = (key: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const save = async () => {
    if (!group) return;
    setBusy(true);
    setError(null);
    try {
      const resources = all
        .filter((resource) => selected.has(`${resource.type}-${resource.id}`))
        .map((resource) => ({ type: resource.type, id: resource.id }));
      await api<ResourceGroup>(`/v1/workspaces/${ws}/resource-groups/${group.id}/resources`, {
        method: "PUT",
        body: JSON.stringify({ resources }),
      });
      navigate(`/groups/${group.id}`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not save membership");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Shell
      title="Add resources"
      suffix="Resource group"
      subtitle={group?.name ?? id}
      icon="layers"
      crumbs={[
        { label: "Resource Manager" },
        { label: "Resource groups", to: "/groups" },
        { label: group?.name ?? "Resource group", to: id ? `/groups/${id}` : undefined },
        { label: "Resources" },
      ]}
      commands={[
        {
          label: busy ? "Saving…" : "Save",
          icon: "check",
          primary: true,
          disabled: busy || !group,
          onClick: save,
        },
        {
          label: "Cancel",
          icon: "close",
          onClick: () => navigate(id ? `/groups/${id}` : "/groups"),
        },
      ]}
    >
      {inventory.error ? <ErrorBox error={inventory.error} onRetry={inventory.reload} /> : null}
      {inventory.loading ? (
        <Skeleton rows={6} />
      ) : !group ? (
        <div className="callout">
          This resource group does not exist. <Link to="/groups">Back to resource groups</Link>.
        </div>
      ) : (
        <div className="panel form-panel">
          <div className="panel__header">
            <h2>Membership</h2>
            <div className="panel__actions">
              <span className="muted small">
                {selected.size} of {all.length} resources selected
              </span>
            </div>
          </div>
          <div className="panel__body">
            <p className="muted small" style={{ marginTop: 0 }}>
              Moving a resource into this group changes ownership and navigation. Removing it
              leaves the resource standalone; grants keep working either way.
            </p>
            {error ? <div className="callout callout--error">{error}</div> : null}
            <div className="check-list">
              {all.map((resource) => {
                const key = `${resource.type}-${resource.id}`;
                return (
                  <label className="check-row" key={key}>
                    <input
                      type="checkbox"
                      checked={selected.has(key)}
                      onChange={() => toggle(key)}
                    />
                    <span className="check-row__main">
                      <span className="cell-name">{resource.name}</span>
                      <span className="muted small">
                        {resource.type} · {resource.kind}
                      </span>
                    </span>
                    <StatusBadge status={resource.status} />
                    <span className="muted small">{resource.group_id ? "in a group" : "standalone"}</span>
                  </label>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </Shell>
  );
}
