import type { ReactNode } from "react";
import { ApiError } from "../api/client";

export function Skeleton({ lines = 3, label }: { lines?: number; label: string }) {
  return (
    <div className="skeleton" role="status" aria-live="polite" aria-label={label}>
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="skeleton-line" style={{ width: `${92 - i * 14}%` }} />
      ))}
    </div>
  );
}

export function ErrorState({ error, onRetry, what }: { error: unknown; onRetry?: () => void; what: string }) {
  const msg = error instanceof ApiError ? (error.status === 401 ? "Your sign-in has expired. Choose a desk user again." : error.message) : "The desk API did not answer. Check that it is running.";
  return (
    <div className="state state-error" role="alert">
      <p className="state-title">Could not load {what}</p>
      <p className="state-body">{msg}</p>
      {onRetry && (
        <button type="button" className="button" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state state-empty">
      <p className="state-title">{title}</p>
      {children && <div className="state-body">{children}</div>}
    </div>
  );
}
