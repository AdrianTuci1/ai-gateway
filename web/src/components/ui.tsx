import type { ReactNode } from "react";

import { Icon } from "./Icon";
import { ApiError } from "../api";

export function Badge({
  children,
  tone = "plain",
}: {
  children: ReactNode;
  tone?: "ok" | "warn" | "error" | "info" | "plain";
}) {
  return <span className={`badge${tone === "plain" ? " badge--plain" : ` badge--${tone}`}`}>{children}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "active" || status === "approved"
      ? "ok"
      : status === "suspended" ||
          status === "disabled" ||
          status === "revoked" ||
          status === "pending"
        ? "warn"
        : status === "error" || status === "deny" || status === "rejected"
          ? "error"
          : "plain";
  return (
    <Badge tone={tone}>
      <span className="dot" />
      {status}
    </Badge>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <Icon name="grid" size={22} />
      <h3>{title}</h3>
      {children ? <p>{children}</p> : null}
      {action ? <div style={{ marginTop: 16 }}>{action}</div> : null}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const traceId = error instanceof ApiError ? error.traceId : undefined;
  return (
    <div className="callout callout--error" role="alert">
      <div className="row row--between">
        <strong>{error.message}</strong>
        {onRetry ? (
          <button className="btn btn--small" type="button" onClick={onRetry}>
            <Icon name="refresh" size={12} />
            Retry
          </button>
        ) : null}
      </div>
      {traceId ? (
        <div className="mono small" style={{ marginTop: 8 }}>
          trace {traceId}
        </div>
      ) : null}
    </div>
  );
}

export function Skeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="stack" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, index) => (
        <div className="skeleton" key={index} style={{ width: `${100 - index * 7}%` }} />
      ))}
    </div>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {hint ? <span className="field__hint">{hint}</span> : null}
    </div>
  );
}

export function Modal({
  title,
  children,
  onClose,
  footer,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  footer?: ReactNode;
}) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal__header">
          <h2>{title}</h2>
          <button
            className="page-header__close"
            type="button"
            aria-label="Close"
            onClick={onClose}
            style={{ marginLeft: "auto" }}
          >
            <Icon name="close" />
          </button>
        </div>
        <div className="modal__body">{children}</div>
        {footer ? <div className="modal__footer">{footer}</div> : null}
      </div>
    </div>
  );
}
