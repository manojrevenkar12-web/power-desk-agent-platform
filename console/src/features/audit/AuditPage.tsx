import { useQuery } from "@tanstack/react-query";
import { api } from "../../shared/api/client";
import { useSession } from "../../shared/session";
import { EmptyState, ErrorState, Skeleton } from "../../shared/ui/states";

export function AuditPage() {
  const { me } = useSession();
  const q = useQuery({ queryKey: ["audit"], queryFn: api.audit, refetchInterval: 5000 });
  if (q.isPending) return <Skeleton lines={5} label="Loading the tool call log" />;
  if (q.isError) return <ErrorState what="the tool call log" error={q.error} onRetry={() => q.refetch()} />;
  const rows = [...q.data].reverse();
  return (
    <div className="page">
      <header className="page-head">
        <h1 className="page-title">Tool calls</h1>
        <p className="lede">{me?.role === "risk" ? "Every user's calls, as risk sees them." : "Your calls. Risk sees everyone's."} Arguments are stored as a hash, never in clear.</p>
      </header>
      {rows.length === 0 ? (
        <EmptyState title="No tool calls yet">Ask the agent something and its calls appear here.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <caption className="visually-hidden">Tool calls</caption>
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">User</th>
                <th scope="col">Surface</th>
                <th scope="col">Tool</th>
                <th scope="col">Outcome</th>
                <th scope="col">Arguments hash</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.call_id}>
                  <td>{new Date(r.at * 1000).toLocaleTimeString("en-GB")}</td>
                  <td>{r.user}</td>
                  <td>{r.surface === "developer_tools" ? "developer tools" : "desk agent"}</td>
                  <td>{r.tool}</td>
                  <td className={r.ok ? "good" : "bad"}>{r.ok ? "ran" : r.denied_by.length ? `refused (${r.denied_by.join(", ")})` : r.error}</td>
                  <td>
                    <code>{r.args_sha256}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
