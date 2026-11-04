import { fmtDuration, type TraceSpan } from "../api";

/**
 * Timeline of a trace: each span is positioned relative to the earliest span in
 * the set, so parents and children line up in one shared scale.
 */
export function Waterfall({ spans }: { spans: TraceSpan[] }) {
  if (spans.length === 0) return null;

  const start = Math.min(...spans.map((span) => Date.parse(span.started_at)));
  const end = Math.max(
    ...spans.map((span) => Date.parse(span.started_at) + Math.max(span.duration_ms, 0)),
  );
  const total = Math.max(end - start, 1);

  const byId = new Map(spans.map((span) => [span.span_id, span]));
  const depthOf = (span: TraceSpan): number => {
    let depth = 0;
    let current = span.parent_span_id;
    const seen = new Set<string>();
    while (current && byId.has(current) && depth < 6 && !seen.has(current)) {
      seen.add(current);
      depth += 1;
      current = byId.get(current)?.parent_span_id ?? null;
    }
    return depth;
  };

  const ordered = [...spans].sort(
    (left, right) => Date.parse(left.started_at) - Date.parse(right.started_at),
  );

  return (
    <div className="waterfall">
      {ordered.map((span) => {
        const offset = Math.max(Date.parse(span.started_at) - start, 0);
        const left = (offset / total) * 100;
        const width = Math.max((Math.max(span.duration_ms, 1) / total) * 100, 0.4);
        const depth = depthOf(span);
        return (
          <div className="waterfall__row" key={span.span_id}>
            <div className="waterfall__name" style={{ paddingLeft: depth * 14 }}>
              <span className="truncate" title={span.name}>
                {span.name}
              </span>
              <small>
                {span.kind} · {span.span_id}
              </small>
            </div>
            <div className="waterfall__track">
              <div
                className={`waterfall__bar${span.status === "error" ? " is-error" : ""}`}
                style={{ left: `${left}%`, width: `${width}%` }}
                title={`${span.name} — ${fmtDuration(span.duration_ms)}`}
              />
            </div>
            <div className="waterfall__duration">{fmtDuration(span.duration_ms)}</div>
          </div>
        );
      })}
    </div>
  );
}
