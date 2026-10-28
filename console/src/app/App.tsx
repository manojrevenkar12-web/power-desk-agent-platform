import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { AskPage } from "../features/ask/AskPage";
import { AuditPage } from "../features/audit/AuditPage";
import { ConnectorsPage } from "../features/connectors/ConnectorsPage";
import { EvalsPage } from "../features/evals/EvalsPage";
import { RolloutPage } from "../features/rollout/RolloutPage";
import { api } from "../shared/api/client";
import { useSession } from "../shared/session";
import { ErrorState, Skeleton } from "../shared/ui/states";

const PAGES = [
  { id: "ask", label: "Ask", el: <AskPage /> },
  { id: "evals", label: "Measurements", el: <EvalsPage /> },
  { id: "connectors", label: "Frameworks", el: <ConnectorsPage /> },
  { id: "rollout", label: "Claude Code rollout", el: <RolloutPage /> },
  { id: "audit", label: "Tool calls", el: <AuditPage /> },
] as const;
type PageId = (typeof PAGES)[number]["id"];

function useHashPage(): [PageId, (p: PageId) => void] {
  const read = () => (PAGES.find((p) => `#${p.id}` === window.location.hash)?.id ?? "ask") as PageId;
  const [page, setPage] = useState<PageId>(read);
  useEffect(() => {
    const on = () => setPage(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return [page, (p) => (window.location.hash = p)];
}

function SignIn() {
  const { signIn } = useSession();
  const users = useQuery({ queryKey: ["users"], queryFn: api.users });
  const [busy, setBusy] = useState<string | null>(null);
  return (
    <main className="signin" id="main">
      <h1 className="signin-title">Power desk</h1>
      <p className="lede">The desk's research agent. Every number it states is traced to a tool result; every tool call is checked against desk policy. Choose who you are (fictional desk users, dev sign-in).</p>
      {users.isPending ? (
        <Skeleton lines={3} label="Loading desk users" />
      ) : users.isError ? (
        <ErrorState what="desk users" error={users.error} onRetry={() => users.refetch()} />
      ) : (
        <ul className="user-grid">
          {users.data.map((u) => (
            <li key={u.id}>
              <button
                type="button"
                className="user-card"
                disabled={busy !== null}
                onClick={async () => {
                  setBusy(u.id);
                  try {
                    await signIn(u.id);
                  } finally {
                    setBusy(null);
                  }
                }}
              >
                <span className="user-name">{u.name}</span>
                <span className="user-role">
                  {u.role}, {u.desk}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<string>(() => document.documentElement.dataset.theme ?? "system");
  useEffect(() => {
    if (theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
  }, [theme]);
  return (
    <label className="field-inline">
      <span className="visually-hidden">Theme</span>
      <select value={theme} onChange={(e) => setTheme(e.target.value)} aria-label="Theme">
        <option value="system">System theme</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </label>
  );
}

export function App() {
  const { me, loading, error, signOut, retry } = useSession();
  const [page, setPage] = useHashPage();
  if (loading) return <Skeleton lines={4} label="Signing in" />;
  if (error && !me) return <ErrorState what="your desk profile" error={error} onRetry={retry} />;
  if (!me) return <SignIn />;
  const current = PAGES.find((p) => p.id === page)!;
  return (
    <div className="shell">
      <a href="#main" className="skip">
        Skip to content
      </a>
      <header className="topbar">
        <span className="brand">Power desk</span>
        <nav aria-label="Sections" className="nav">
          {PAGES.map((p) => (
            <a key={p.id} href={`#${p.id}`} className="nav-link" aria-current={p.id === page ? "page" : undefined} onClick={() => setPage(p.id)}>
              {p.label}
            </a>
          ))}
        </nav>
        <div className="who">
          <span className="who-name">{me.name}</span>
          <span className="who-role">
            {me.role}, {me.desk}; {me.books.length ? `books ${me.books.join(", ")}` : "no book access"}
          </span>
          <ThemeToggle />
          <button type="button" className="button" onClick={signOut}>
            Switch user
          </button>
        </div>
      </header>
      <main id="main" tabIndex={-1}>
        {current.el}
      </main>
    </div>
  );
}
