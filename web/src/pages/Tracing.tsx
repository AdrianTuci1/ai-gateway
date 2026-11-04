import { useState } from "react";
import { Link } from "react-router-dom";

import {
  api,
  apiPage,
  fmtDate,
  fmtDuration,
  getWorkspace,
  type TraceDetail as TraceDetailData,
  type TraceSummary,
} from "../api";
import { DataTable, type Column, type TableRow } from "../components/DataTable";
import { Pagination } from "../components/Pagination";
import { Shell } from "../components/Shell";
import { ErrorBox, Skeleton, StatusBadge } from "../components/ui";
import { Waterfall } from "../components/Waterfall";
import { useAsync, usePage } from "../hooks";

const PAGE_SIZE = 50;

export function Tracing() {
  const ws = getWorkspace();
  const traces = usePage(
    (page, snapshot) =>
      apiPage<TraceSummary>(
        `/v1/workspaces/${ws}/traces?limit=${PAGE_SIZE}&page=${page}${
          snapshot ? `&as_of=${encodeURIComponent(snapshot)}` : ""
        }`,
      ),
    [ws],
  );
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"all" | "ok" | "error">("all");

  const all = traces.items;
  const visible = all
    .filter((trace) => status === "all" || trace.status === status)
    .filter((trace) =>
      `${trace.root_name} ${trace.trace_id} ${trace.actor_type ?? ""} ${trace.actor_id ?? ""}`
        .toLowerCase()
        .includes(query.toLowerCase()),
    );
  const errors = all.filter((trace) => trace.status === "error").length;
  const durations = all.map((trace) => trace.duration_ms).sort((left, right) => left - right);
  const p95 = durations.length > 0 ? durations[Math.floor((durations.length - 1) * 0.95)] : 0;

  const columns: Column<TraceSummary>[] = [
    {
      key: "operation",
      header: "Operation",
      width: "260px",
      truncate: true,
      render: (trace) => (
        <span className="cell-name">
          <Link to={`/tracing/${trace.trace_id}`} title={trace.root_name}>
            {trace.root_name}
          </Link>
        </span>
      ),
    },
    {
      key: "trace",
      header: "Trace ID",
      width: "230px",
      truncate: true,
      render: (trace) => (
        <Link to={`/tracing/${trace.trace_id}`} className="mono muted">
          {trace.trace_id}
        </Link>
      ),
    },
    {
      key: "spans",
      header: "Spans",
      width: "80px",
      align: "right",
      render: (trace) => trace.span_count,
    },
    {
      key: "duration",
      header: "Duration",
      width: "110px",
      align: "right",
      render: (trace) => <span className="mono">{fmtDuration(trace.duration_ms)}</span>,
    },
    {
      key: "status",
      header: "Status",
      width: "110px",
      render: (trace) => <StatusBadge status={trace.status} />,
    },
    {
      key: "actor",
      header: "Actor",
      width: "200px",
      render: (trace) =>
        trace.actor_type ? (
          <span>
            {trace.actor_type}
            <span className="muted mono"> {trace.actor_id?.slice(0, 8) ?? ""}</span>
          </span>
        ) : (
          <span className="muted">—</span>
        ),
    },
    {
      key: "started",
      header: "Started",
      width: "180px",
      render: (trace) => <span className="nowrap">{fmtDate(trace.started_at)}</span>,
    },
  ];

  const rows: TableRow<TraceSummary>[] = visible.map((trace) => ({
    key: trace.trace_id,
    data: trace,
    nestedTitle: "Waterfall",
    children: <TracePreview traceId={trace.trace_id} />,
  }));

  return (
    <Shell
      title="AI Gateway"
      suffix="Tracing"
      subtitle={`${ws} · ${traces.total} traces`}
      icon="trace"
      crumbs={[{ label: "Observability" }, { label: "Tracing" }]}
      commands={[
        { label: "Refresh", icon: "refresh", primary: true, onClick: traces.reload },
        { label: "Audit log", icon: "audit", onClick: () => { window.location.assign("/audit"); } },
      ]}
    >
      {traces.error ? <ErrorBox error={traces.error} onRetry={traces.reload} /> : null}

      <div className="stat-row" style={{ marginBottom: 12 }}>
        <Stat label="Traces" value={String(traces.total)} />
        <Stat
          label="Errors (page)"
          value={String(errors)}
          tone={errors > 0 ? "error" : undefined}
        />
        <Stat label="p95 (page)" value={fmtDuration(p95)} />
        <Stat
          label="Spans (page)"
          value={String(all.reduce((sum, trace) => sum + trace.span_count, 0))}
        />
      </div>

      <div className="filters">
        <div className="topbar__search" style={{ maxWidth: 360 }}>
          <span aria-hidden="true">⌕</span>
          <input
            aria-label="Filter traces"
            placeholder="Filter by operation, trace or actor"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="trace-status">Status</label>
          <select
            id="trace-status"
            value={status}
            onChange={(event) => setStatus(event.target.value as "all" | "ok" | "error")}
          >
            <option value="all">All statuses</option>
            <option value="ok">OK</option>
            <option value="error">Error</option>
          </select>
        </div>
        <span className="muted small" style={{ marginLeft: "auto" }}>
          {visible.length} of {all.length} on this page · expand a row for its waterfall
        </span>
      </div>

      {traces.loading ? (
        <Skeleton rows={7} />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={rows}
            empty="No traces recorded yet"
            emptyAction={
              <span className="muted small">
                Call any /v1 or /mcp endpoint; each request writes a span.
              </span>
            }
          />
          <Pagination
            page={traces.page}
            pageSize={PAGE_SIZE}
            total={traces.total}
            onPage={traces.goTo}
            disabled={traces.loading}
          />
        </>
      )}
    </Shell>
  );
}

function TracePreview({ traceId }: { traceId: string }) {
  const ws = getWorkspace();
  const trace = useAsync(
    () => api<TraceDetailData>(`/v1/workspaces/${ws}/traces/${traceId}`),
    [ws, traceId],
  );

  if (trace.loading) return <Skeleton rows={2} />;
  if (trace.error) return <ErrorBox error={trace.error} onRetry={trace.reload} />;

  return (
    <div className="stack">
      <Waterfall spans={trace.data?.spans ?? []} />
      <div>
        <Link className="btn btn--small" to={`/tracing/${traceId}`}>
          Open trace
        </Link>
      </div>
    </div>
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
