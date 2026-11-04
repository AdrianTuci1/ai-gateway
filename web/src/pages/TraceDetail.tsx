import { Link, useNavigate, useParams } from "react-router-dom";

import {
  api,
  fmtDate,
  fmtDuration,
  getWorkspace,
  type TraceDetail as TraceDetailData,
  type TraceSpan,
} from "../api";
import { DataTable, type Column, type TableRow } from "../components/DataTable";
import { Shell } from "../components/Shell";
import { ErrorBox, Skeleton, StatusBadge } from "../components/ui";
import { Waterfall } from "../components/Waterfall";
import { useAsync } from "../hooks";

export function TraceDetail() {
  const { traceId } = useParams();
  const ws = getWorkspace();
  const navigate = useNavigate();
  const trace = useAsync(
    () => api<TraceDetailData>(`/v1/workspaces/${ws}/traces/${traceId ?? ""}`),
    [ws, traceId],
  );

  const spans = trace.data?.spans ?? [];
  const ordered = [...spans].sort(
    (left, right) => Date.parse(left.started_at) - Date.parse(right.started_at),
  );
  const start = ordered.length > 0 ? Date.parse(ordered[0].started_at) : 0;
  const root = ordered.find((span) => span.parent_span_id === null) ?? ordered[0];
  const duration =
    ordered.length > 0
      ? Math.max(
          ...ordered.map(
            (span) => Date.parse(span.started_at) - start + Math.max(span.duration_ms, 0),
          ),
        )
      : 0;
  const failed = ordered.some((span) => span.status === "error");

  const columns: Column<TraceSpan>[] = [
    {
      key: "name",
      header: "Span",
      render: (span) => <span className="mono">{span.name}</span>,
    },
    { key: "kind", header: "Kind", width: "110px", render: (span) => span.kind },
    {
      key: "status",
      header: "Status",
      width: "110px",
      render: (span) => <StatusBadge status={span.status} />,
    },
    {
      key: "offset",
      header: "Offset",
      width: "110px",
      align: "right",
      render: (span) => (
        <span className="mono muted">{Math.max(Date.parse(span.started_at) - start, 0)} ms</span>
      ),
    },
    {
      key: "duration",
      header: "Duration",
      width: "110px",
      align: "right",
      render: (span) => <span className="mono">{fmtDuration(span.duration_ms)}</span>,
    },
    {
      key: "actor",
      header: "Actor",
      width: "170px",
      render: (span) =>
        span.actor_type ? (
          <span>
            {span.actor_type}
            <span className="muted mono"> {span.actor_id?.slice(0, 8) ?? ""}</span>
          </span>
        ) : (
          <span className="muted">—</span>
        ),
    },
    {
      key: "started",
      header: "Started",
      width: "180px",
      render: (span) => <span className="nowrap">{fmtDate(span.started_at)}</span>,
    },
  ];

  const rows: TableRow<TraceSpan>[] = ordered.map((span) => ({
    key: span.span_id,
    data: span,
    nestedTitle: "Attributes",
    children: <pre className="code-block">{JSON.stringify(span.attributes ?? {}, null, 2)}</pre>,
  }));

  return (
    <Shell
      title={root?.name ?? "Trace"}
      suffix="Trace"
      subtitle={traceId}
      icon="trace"
      crumbs={[
        { label: "Observability" },
        { label: "Tracing", to: "/tracing" },
        { label: traceId ? traceId.slice(0, 16) : "trace" },
      ]}
      commands={[
        { label: "Refresh", icon: "refresh", primary: true, onClick: trace.reload },
        { label: "All traces", icon: "trace", onClick: () => navigate("/tracing") },
      ]}
    >
      {trace.error ? <ErrorBox error={trace.error} onRetry={trace.reload} /> : null}

      {trace.loading ? (
        <Skeleton rows={6} />
      ) : root ? (
        <>
          <div className="stat-row">
            <Stat label="Duration" value={fmtDuration(duration)} />
            <Stat label="Spans" value={String(ordered.length)} />
            <Stat
              label="Status"
              value={failed ? "error" : root.status}
              tone={failed || root.status === "error" ? "error" : "ok"}
            />
            <Stat label="Started" value={fmtDate(root.started_at)} />
          </div>

          <div className="grid grid--sidebar" style={{ marginTop: 16 }}>
            <section>
              <div className="section-title">Waterfall</div>
              <Waterfall spans={ordered} />
              <p className="muted small">
                Bars share one time scale from the first span. Indentation follows the
                <span className="mono"> parent_span_id </span> chain.
              </p>
            </section>

            <section className="panel">
              <div className="panel__header">
                <h2>Trace properties</h2>
                <div className="panel__actions">
                  <StatusBadge status={failed ? "error" : root.status} />
                </div>
              </div>
              <div className="panel__body">
                <dl className="kv">
                  <dt>Trace ID</dt>
                  <dd className="mono truncate">{traceId}</dd>
                  <dt>Root span</dt>
                  <dd className="mono">{root.span_id}</dd>
                  <dt>Kind</dt>
                  <dd>{root.kind}</dd>
                  <dt>Actor</dt>
                  <dd>
                    {root.actor_type ? (
                      <>
                        {root.actor_type}
                        <span className="mono muted"> {root.actor_id}</span>
                      </>
                    ) : (
                      <span className="muted">unknown</span>
                    )}
                  </dd>
                  <dt>Started</dt>
                  <dd>{fmtDate(root.started_at)}</dd>
                  <dt>Spans</dt>
                  <dd>{ordered.length}</dd>
                </dl>
                <div className="section-title">Root attributes</div>
                <pre className="code-block">{JSON.stringify(root.attributes ?? {}, null, 2)}</pre>
                <div style={{ marginTop: 12 }}>
                  <Link className="btn btn--small" to="/audit">
                    Related audit events
                  </Link>
                </div>
              </div>
            </section>
          </div>

          <div className="section-title">Spans</div>
          <DataTable columns={columns} rows={rows} empty="This trace has no spans." />
        </>
      ) : null}
    </Shell>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "ok" | "error";
}) {
  const color =
    tone === "error" ? "var(--danger)" : tone === "ok" ? "var(--success)" : undefined;
  return (
    <div className="stat">
      <div className="stat__value" style={color ? { color } : undefined}>
        {value}
      </div>
      <div className="stat__label">{label}</div>
    </div>
  );
}
