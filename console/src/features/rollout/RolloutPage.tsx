import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../shared/api/client";
import { EmptyState, ErrorState, Skeleton } from "../../shared/ui/states";

export function RolloutPage() {
  const q = useQuery({ queryKey: ["rollout"], queryFn: api.rollout });
  const [team, setTeam] = useState<string | null>(null);
  if (q.isPending) return <Skeleton lines={6} label="Loading rollout settings" />;
  if (q.isError) return <ErrorState what="rollout settings" error={q.error} onRetry={() => q.refetch()} />;
  const names = Object.keys(q.data.teams);
  if (names.length === 0) return <EmptyState title="No teams configured">Add teams to config/rollout.yaml.</EmptyState>;
  const current = team ?? names[0]!;
  const t = q.data.teams[current]!;
  return (
    <div className="page">
      <header className="page-head">
        <h1 className="page-title">Claude Code for each team, through Bedrock in the EU</h1>
        <p className="lede">
          These files are deployed by MDM. On Bedrock, Claude Code does not fetch server-managed settings, so policy arrives as files at{" "}
          {Object.values(q.data.paths).map((p, i, a) => (
            <span key={p}>
              <code>{p}</code>
              {i < a.length - 1 ? ", " : ""}
            </span>
          ))}
          .
        </p>
      </header>
      <div className="tabs" role="tablist" aria-label="Team">
        {names.map((n) => (
          <button key={n} role="tab" type="button" aria-selected={n === current} className="tab" onClick={() => setTeam(n)}>
            {n}
          </button>
        ))}
      </div>
      <section className="panel" role="tabpanel" aria-label={current}>
        <p className="muted">{t.description}</p>
        <p className={t.problems.length ? "bad" : "good"}>{t.problems.length ? `${t.problems.length} problems: ${t.problems.join("; ")}` : "Valid against the documented rules"}</p>
        <div className="code-grid">
          <div>
            <h2 className="sub-title">managed-settings.json</h2>
            <pre className="code">{JSON.stringify(t.managed_settings, null, 2)}</pre>
          </div>
          <div>
            <h2 className="sub-title">managed-mcp.json</h2>
            <pre className="code">{JSON.stringify(t.managed_mcp, null, 2)}</pre>
          </div>
        </div>
      </section>
    </div>
  );
}
