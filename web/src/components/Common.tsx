import type { ReactNode } from "react";
import { ApiError } from "../api";
import type { Role } from "../types";

export function Card({
  title,
  children,
  actions,
  className,
}: {
  title?: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card${className ? ` ${className}` : ""}`}>
      {(title || actions) && (
        <header className="card-head">
          {title && <h2 className="card-title">{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

/** Renders a friendly, RBAC-aware error message instead of crashing. */
export function ErrorNote({ error, role }: { error: unknown; role: Role }) {
  let message = "Something went wrong.";
  if (error instanceof ApiError) {
    if (error.isForbidden) {
      message = `Your current role (${role}) can't do this. Switch roles using the dropdown above.`;
    } else if (error.status === 404) {
      message = error.message || "Not found.";
    } else {
      message = error.message;
    }
  } else if (error instanceof Error) {
    message = error.message;
  }
  return (
    <div className="error-note" role="alert">
      {message}
    </div>
  );
}

/** Inline key/value detail rows used inside trace steps and metrics. */
export function KeyVal({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="kv">
      <span className="kv-k">{k}</span>
      <span className="kv-v">{v}</span>
    </div>
  );
}
