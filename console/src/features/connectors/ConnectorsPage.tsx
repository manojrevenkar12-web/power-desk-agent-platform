import { useQuery } from "@tanstack/react-query";
import { api } from "../../shared/api/client";
import { EmptyState, ErrorState, Skeleton } from "../../shared/ui/states";

export function ConnectorsPage() {
  const q = useQuery({ queryKey: ["connectors"], queryFn: api.connectors, retry: false });
  if (q.isPending) return <Skeleton lines={5} label="Loading the connector report" />;
  if (q.isError) return <ErrorState what="the connector report" error={q.error} onRetry={() => q.refetch()} />;
  const r = q.data;
  const n8n = r.documented.n8n;
  return (
    <div className="page">
      <header className="page-head">
        <h1 className="page-title">Agent frameworks against the desk's tools</h1>
        <p className="lede">
          Each framework was installed into a clean Python {r.python} environment and pointed at the desk's MCP server with a user's token. Anything it tried on the network, other than the desk server, was blocked and recorded.
        </p>
      </header>
      {r.candidates.length === 0 ? (
        <EmptyState title="No frameworks measured">Add candidates to config/connectors.yaml and run the harness.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <caption className="visually-hidden">Connector fitness</caption>
            <thead>
              <tr>
                <th scope="col">Framework</th>
                <th scope="col" className="num-cell">Packages installed</th>
                <th scope="col" className="num-cell">Size</th>
                <th scope="col" className="num-cell">Import</th>
                <th scope="col" className="num-cell">Network at import</th>
                <th scope="col">Desk tools loaded and called</th>
                <th scope="col">Without a token</th>
                <th scope="col">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {r.candidates.map((c) => (
                <tr key={c.name}>
                  <th scope="row">{c.name}</th>
                  <td className="num-cell">{c.distributions}</td>
                  <td className="num-cell">{c.size_mb} MB</td>
                  <td className="num-cell">{Math.round(c.import_ms_median_of_3)} ms</td>
                  <td className="num-cell">{c.network_attempts_at_import.length}</td>
                  <td>{c.mcp_call_ok ? `yes, ${c.mcp_tools_listed} tools; ${c.dev_surface_book_tools.length} book tools on the developer surface` : "no"}</td>
                  <td>{c.anonymous.startsWith("refused") ? "refused" : c.anonymous || "not tested"}</td>
                  <td className={c.fit ? "good" : "bad"}>{c.fit ? "Fit" : "Not fit"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {n8n && (
        <section className="panel" aria-labelledby="n8n-title">
          <h2 id="n8n-title" className="panel-title">
            n8n, from its documentation
          </h2>
          <dl className="evidence-list">
            <dt>Licence</dt>
            <dd>
              {n8n.licence} <a href={n8n.licence_source}>Source</a>
            </dd>
            <dt>Network by default</dt>
            <dd>
              {n8n.network_by_default} <a href={n8n.network_source}>Source</a>
            </dd>
            <dt>MCP</dt>
            <dd>
              {n8n.mcp} <a href={n8n.mcp_source}>Source</a>
            </dd>
          </dl>
        </section>
      )}
    </div>
  );
}
