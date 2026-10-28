import { useMutation } from "@tanstack/react-query";
import { motion, useReducedMotion } from "motion/react";
import { type FormEvent, useState } from "react";
import { type Answer, api } from "../../shared/api/client";
import { useSession } from "../../shared/session";
import { motionTokens } from "../../shared/theme/tokens";
import { EmptyState, ErrorState, Skeleton } from "../../shared/ui/states";
import { AnswerText, EvidenceCard, ToolTrace } from "./Answer";
import { PriceStrip } from "./PriceStrip";
import { SUGGESTIONS } from "./suggestions";

export function AskPage() {
  const { me } = useSession();
  const reduce = useReducedMotion();
  const [question, setQuestion] = useState("");
  const [surface, setSurface] = useState<"desk_agent" | "developer_tools">("desk_agent");
  const [attach, setAttach] = useState(false);
  const [attachText, setAttachText] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const ask = useMutation({
    mutationFn: (q: string) => api.ask({ question: q, surface, ...(attach && attachText ? { attach_title: "Pasted note", attach_text: attachText } : {}) }),
    onSuccess: (a: Answer) => {
      const o = [...a.numbers].sort((x, y) => x.start - y.start);
      const untraced = o.findIndex((n) => !n.grounded);
      setSelected(untraced >= 0 ? untraced : o.length ? 0 : null);
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (question.trim()) ask.mutate(question.trim());
  };
  const answer = ask.data;
  const ordered = answer ? [...answer.numbers].sort((a, b) => a.start - b.start) : [];
  const check = selected !== null ? ordered[selected] : undefined;

  return (
    <div className="page">
      <PriceStrip />
      <div className="ask-grid">
        <section aria-labelledby="ask-title" className="panel">
          <h2 id="ask-title" className="panel-title">
            Ask the desk agent
          </h2>
          <form onSubmit={submit} className="composer">
            <label htmlFor="question" className="visually-hidden">
              Question
            </label>
            <textarea id="question" rows={3} value={question} placeholder="For example: average FR day-ahead price in August 2026" onChange={(e) => setQuestion(e.target.value)} />
            <div className="composer-row">
              <fieldset className="segmented">
                <legend className="visually-hidden">Ask from</legend>
                <label>
                  <input type="radio" name="surface" checked={surface === "desk_agent"} onChange={() => setSurface("desk_agent")} /> Desk agent
                </label>
                <label>
                  <input type="radio" name="surface" checked={surface === "developer_tools"} onChange={() => setSurface("developer_tools")} /> Developer tools
                </label>
              </fieldset>
              <label className="check">
                <input type="checkbox" checked={attach} onChange={(e) => setAttach(e.target.checked)} /> Attach a note
              </label>
              <button type="submit" className="button button-primary" disabled={!question.trim() || ask.isPending}>
                {ask.isPending ? "Asking" : "Ask"}
              </button>
            </div>
            {attach && (
              <>
                <label htmlFor="attach" className="field-label">
                  Note for this chat only
                </label>
                <textarea id="attach" rows={3} value={attachText} onChange={(e) => setAttachText(e.target.value)} />
              </>
            )}
          </form>
          {me && (
            <div className="suggestions">
              <p className="muted">Try, as {me.name}:</p>
              <ul>
                {(SUGGESTIONS[me.id] ?? []).map((s) => (
                  <li key={s.q}>
                    <button type="button" className="suggestion" onClick={() => setQuestion(s.q)}>
                      {s.q}
                    </button>
                    {s.note && <span className="suggestion-note">{s.note}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="answer" aria-live="polite">
            {ask.isPending ? (
              <Skeleton lines={4} label="The agent is working" />
            ) : ask.isError ? (
              <ErrorState what="an answer" error={ask.error} onRetry={() => ask.mutate(question.trim())} />
            ) : answer ? (
              <motion.div initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: motionTokens.calm }}>
                <AnswerText answer={answer} selected={selected} onSelect={setSelected} />
                <p className="answer-meta">
                  {answer.numbers.length} numbers checked, {answer.numbers.filter((n) => n.grounded).length} traced
                  {answer.corrections ? `; the grounding check sent it back ${answer.corrections === 1 ? "once" : `${answer.corrections} times`}` : ""}
                  {answer.redacted ? "; untraced numbers removed" : ""}. {answer.model_calls} model calls.
                </p>
              </motion.div>
            ) : (
              <EmptyState title="No question yet">Ask about prices, PPAs, batteries, hedges or desk rules. Every number in the answer links to where it came from.</EmptyState>
            )}
          </div>
        </section>
        <aside className="panel" aria-labelledby="trace-title">
          <h2 id="trace-title" className="panel-title">
            Where the numbers came from
          </h2>
          {answer ? (
            <>
              {check ? <EvidenceCard check={check} calls={answer.tool_calls} /> : <p className="muted">This answer has no numbers.</p>}
              <h3 className="sub-title">Tool calls</h3>
              <ToolTrace calls={answer.tool_calls} skill={answer.skill} />
            </>
          ) : (
            <EmptyState title="Nothing to trace yet">Select a number in an answer to see the tool and field it came from, and which calls policy refused.</EmptyState>
          )}
        </aside>
      </div>
    </div>
  );
}
