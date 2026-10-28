import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import type { Answer as AnswerT, NumberCheck, ToolCall } from "../../shared/api/client";
import { motionTokens } from "../../shared/theme/tokens";
import { segments, valueAt } from "./segments";

export function AnswerText({ answer, selected, onSelect }: { answer: AnswerT; selected: number | null; onSelect: (i: number) => void }) {
  const parts = segments(answer.answer, answer.numbers);
  return (
    <p className="answer-text">
      {parts.map((s, i) =>
        s.kind === "text" ? (
          <span key={i}>{s.text}</span>
        ) : (
          <button
            key={i}
            type="button"
            className={`num ${s.check.grounded ? "num-traced" : "num-untraced"}`}
            aria-pressed={selected === s.index}
            aria-label={`${s.text}: ${s.check.grounded ? `from ${s.check.source}` : "not traced to any tool result"}`}
            onClick={() => onSelect(s.index)}
          >
            {s.text}
          </button>
        ),
      )}
    </p>
  );
}

export function EvidenceCard({ check, calls }: { check: NumberCheck; calls: ToolCall[] }) {
  const reduce = useReducedMotion();
  const call = calls.find((c) => c.call_id === check.source);
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={`${check.text}-${check.start}`}
        className={`evidence ${check.grounded ? "" : "evidence-untraced"}`}
        initial={reduce ? false : { opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        exit={reduce ? undefined : { opacity: 0 }}
        transition={{ duration: motionTokens.quick, ease: motionTokens.ease }}
      >
        <p className="evidence-value">{check.text}</p>
        {check.grounded ? (
          <dl className="evidence-list">
            <dt>Returned by</dt>
            <dd>{call ? call.name : check.source}</dd>
            <dt>Field</dt>
            <dd>
              <code>{check.path}</code>
            </dd>
            <dt>Value there</dt>
            <dd>{call?.result && check.path ? String(valueAt(call.result, check.path)) : "in a document"}</dd>
            <dt>Call</dt>
            <dd>
              <code>{check.source}</code>
            </dd>
          </dl>
        ) : (
          <p className="evidence-note">No tool result or document contains this number, so it is not shown as fact.</p>
        )}
      </motion.div>
    </AnimatePresence>
  );
}

export function ToolTrace({ calls, skill }: { calls: ToolCall[]; skill: string | null }) {
  if (calls.length === 0) return <p className="muted">The agent answered without calling a tool.</p>;
  return (
    <ol className="trace">
      {skill && (
        <li className="trace-step">
          <span className="trace-name">Skill</span>
          <span className="trace-args">{skill}</span>
        </li>
      )}
      {calls.map((c) => (
        <li key={c.call_id} className={`trace-step ${c.ok ? "trace-ok" : c.denied_by.length ? "trace-denied" : "trace-error"}`}>
          <span className="trace-name">{c.name}</span>
          <span className="trace-args">
            {Object.entries(c.input)
              .map(([k, v]) => `${k} ${Array.isArray(v) ? v.join(", ") : String(v)}`)
              .join("; ")}
          </span>
          {!c.ok && (
            <span className="trace-why">
              {c.denied_by.length ? "Refused by policy " : ""}
              {c.denied_by.length ? <code>{c.denied_by.join(", ")}</code> : c.error}
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}
