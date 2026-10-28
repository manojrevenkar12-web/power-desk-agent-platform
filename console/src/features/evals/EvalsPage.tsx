import { useQuery } from "@tanstack/react-query";
import { api, type SuiteSummary } from "../../shared/api/client";
import { EmptyState, ErrorState, Skeleton } from "../../shared/ui/states";

const SUITES: { key: "dev" | "redteam" | "ablation"; title: string; what: string }[] = [
  { key: "dev", title: "Development suite", what: "Questions from all six desk users, with figures computed by a second, independent implementation." },
  { key: "redteam", title: "Red team", what: "A model that obeys instructions planted in documents. Policy at the gateway has to stop what it then tries." },
  { key: "ablation", title: "Grounding switched off", what: "The development suite with the grounding check disabled, to show what it catches." },
];

function Figures({ s }: { s: SuiteSummary }) {
  return (
    <dl className="figures">
      <div>
        <dt>Cases passed</dt>
        <dd>
          {s.passed} of {s.cases}
        </dd>
      </div>
      <div>
        <dt>Expected figures stated correctly</dt>
        <dd>{s.numbers_expected ? `${s.numbers_correct} of ${s.numbers_expected}` : "none expected"}</dd>
      </div>
      <div>
        <dt>Answers that leaked something</dt>
        <dd className={s.leaks ? "bad" : "good"}>{s.leaks}</dd>
      </div>
      <div>
        <dt>Untraced numbers shown to a user</dt>
        <dd className={s.untraced_numbers_shipped ? "bad" : "good"}>{s.untraced_numbers_shipped}</dd>
      </div>
      <div>
        <dt>Tool calls refused by policy</dt>
        <dd>{s.tool_calls_denied_by_policy}</dd>
      </div>
    </dl>
  );
}

export function EvalsPage() {
  const q = useQuery({ queryKey: ["evals"], queryFn: api.evals });
  if (q.isPending) return <Skeleton lines={6} label="Loading evaluation reports" />;
  if (q.isError) return <ErrorState what="evaluation reports" error={q.error} onRetry={() => q.refetch()} />;
  const e = q.data;
  const blind = Object.entries(e.heldout);
  const any = SUITES.some((s) => e[s.key]);
  return (
    <div className="page">
      <header className="page-head">
        <h1 className="page-title">How the agent is measured</h1>
        <p className="lede">Each suite runs the real gateway, policies, knowledge base and grounding check against a simulated model, so the results reproduce exactly in CI.</p>
      </header>
      {!any && <EmptyState title="No reports yet">Run the evaluation suites to produce them.</EmptyState>}
      <div className="suite-grid">
        {SUITES.map(({ key, title, what }) => {
          const r = e[key];
          return r ? (
            <section key={key} className="panel" aria-labelledby={`suite-${key}`}>
              <h2 id={`suite-${key}`} className="panel-title">
                {title}
              </h2>
              <p className="muted">{what}</p>
              <Figures s={r.summary} />
              {r.summary.failed.length > 0 && <p className="muted">Failed: {r.summary.failed.join(", ")}</p>}
            </section>
          ) : null;
        })}
      </div>
      <section className="panel" aria-labelledby="blind-title">
        <h2 id="blind-title" className="panel-title">
          Blind held-out set
        </h2>
        {blind.length === 0 ? (
          <EmptyState title="No first run recorded">A held-out set counts only from its first run, which is recorded once and never rewritten.</EmptyState>
        ) : (
          blind.map(([name, b]) => (
            <div key={name}>
              <p className="muted">
                {name}: written by someone who never saw the code, run once on {b.recorded_at.slice(0, 10)}. This first run is never rewritten; its failures have not been studied.
              </p>
              <Figures s={b.summary} />
            </div>
          ))
        )}
      </section>
    </div>
  );
}
