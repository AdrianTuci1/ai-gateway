import { useState } from "react";
import { Link } from "react-router-dom";

import { apiPage, fmtDate, getWorkspace, type AuditEvent } from "../api";
import { DataTable, type Column, type TableRow } from "../components/DataTable";
import { Pagination } from "../components/Pagination";
import { Shell } from "../components/Shell";
import { Badge, ErrorBox, Skeleton } from "../components/ui";
import { usePage } from "../hooks";

const PAGE_SIZE = 50;

export function Audit() {
  const ws = getWorkspace();
  const [decision, setDecision] = useState<"all" | "allow" | "deny">("all");
  const [query, setQuery] = useState("");

  const audit = usePage(
    (page, snapshot) =>
      apiPage<AuditEvent>(
        `/v1/workspaces/${ws}/audit?limit=${PAGE_SIZE}&page=${page}${
          decision === "all" ? "" : `&decision=${decision}`
        }${snapshot ? `&as_of=${encodeURIComponent(snapshot)}` : ""}`,
      ),
    [ws, decision],
  );

  const all = audit.items;
  const visible = all.filter((event) =>
    `${event.action} ${event.actor_type} ${event.actor_id ?? ""} ${event.resource_type ?? ""} ${
      event.resource_id ?? ""
    } ${event.reason ?? ""}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const denials = all.filter((event) => event.decision === "deny").length;

  const columns: Column<AuditEvent>[] = [
    {
      key: "time",
      header: "Time",
      width: "190px",
      render: (event) => <span className="nowrap">{fmtDate(event.created_at)}</span>,
    },
    {
      key: "actor",
      header: "Actor",
      width: "210px",
      render: (event) => (
        <span>
          {event.actor_type}
          <span className="mono muted"> {event.actor_id?.slice(0, 8) ?? ""}</span>
        </span>
      ),
    },
    {
      key: "action",
      header: "Action",
      render: (event) => <span className="mono">{event.action}</span>,
    },
    {
      key: "resource",
      header: "Resource",
      width: "230px",
      render: (event) =>
        event.resource_type ? (
          <span>
            {event.resource_type}
            <span className="muted"> {event.resource_id?.slice(0, 12) ?? ""}</span>
          </span>
        ) : (
          <span className="muted">—</span>
        ),
    },
    {
      key: "decision",
      header: "Decision",
      width: "110px",
      render: (event) => <Decision decision={event.decision} />,
    },
    {
      key: "reason",
      header: "Reason",
      width: "220px",
      render: (event) => <span className="muted">{event.reason ?? "—"}</span>,
    },
    {
      key: "trace",
      header: "Trace",
      width: "170px",
      render: (event) => (
        <Link className="mono" to={`/tracing/${event.trace_id}`}>
          {event.trace_id.slice(0, 12)}…
        </Link>
      ),
    },
  ];

  const rows: TableRow<AuditEvent>[] = visible.map((event) => ({
    key: event.id,
    data: event,
    nestedTitle: "Event metadata",
    children: (
      <div className="stack">
        <dl className="kv">
          <dt>Event ID</dt>
          <dd className="mono">{event.id}</dd>
          <dt>Trace ID</dt>
          <dd>
            <Link className="mono" to={`/tracing/${event.trace_id}`}>
              {event.trace_id}
            </Link>
          </dd>
          <dt>Reason</dt>
          <dd>{event.reason ?? "—"}</dd>
        </dl>
        <pre className="code-block">{JSON.stringify(event.meta ?? {}, null, 2)}</pre>
      </div>
    ),
  }));

  return (
    <Shell
      title="AI Gateway"
      suffix="Audit log"
      subtitle={`${ws} · ${audit.total} events`}
      icon="audit"
      crumbs={[{ label: "Observability" }, { label: "Audit log" }]}
      commands={[
        { label: "Refresh", icon: "refresh", primary: true, onClick: audit.reload },
        { label: "Tracing", icon: "trace", onClick: () => { window.location.assign("/tracing"); } },
      ]}
    >
      {audit.error ? <ErrorBox error={audit.error} onRetry={audit.reload} /> : null}

      <div className="stat-row" style={{ marginBottom: 12 }}>
        <Stat label="Events" value={String(audit.total)} />
        <Stat
          label="Denials (page)"
          value={String(denials)}
          tone={denials > 0 ? "error" : undefined}
        />
        <Stat
          label="Allowed (page)"
          value={String(all.filter((event) => event.decision === "allow").length)}
        />
      </div>

      <div className="filters">
        <div className="topbar__search" style={{ maxWidth: 360 }}>
          <span aria-hidden="true">⌕</span>
          <input
            aria-label="Filter audit events"
            placeholder="Filter by action, actor or reason"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="audit-decision">Decision</label>
          <select
            id="audit-decision"
            value={decision}
            onChange={(event) =>
              setDecision(event.target.value as "all" | "allow" | "deny")
            }
          >
            <option value="all">All decisions</option>
            <option value="allow">Allow</option>
            <option value="deny">Deny</option>
          </select>
        </div>
        <span className="muted small" style={{ marginLeft: "auto" }}>
          {visible.length} of {all.length} on this page
        </span>
      </div>

      {audit.loading ? (
        <Skeleton rows={8} />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={rows}
            empty="No audit events"
            emptyAction={
              <span className="muted small">
                Administrative changes and MCP tool decisions appear here.
              </span>
            }
          />
          <Pagination
            page={audit.page}
            pageSize={PAGE_SIZE}
            total={audit.total}
            onPage={audit.goTo}
            disabled={audit.loading}
          />
        </>
      )}
    </Shell>
  );
}

function Decision({ decision }: { decision: string | null }) {
  if (!decision) return <Badge>event</Badge>;
  return (
    <Badge tone={decision === "allow" ? "ok" : decision === "deny" ? "error" : "plain"}>
      {decision}
    </Badge>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "error";
}) {
  return (
    <div className="stat">
      <div className="stat__value" style={tone === "error" ? { color: "var(--danger)" } : undefined}>
        {value}
      </div>
      <div className="stat__label">{label}</div>
    </div>
  );
}
