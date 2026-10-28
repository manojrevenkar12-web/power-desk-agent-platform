import type { NumberCheck } from "../../shared/api/client";

export type Segment = { kind: "text"; text: string } | { kind: "number"; text: string; check: NumberCheck; index: number };

/** Split an answer into plain text and checked numbers. Numbers are found by their text, in
 *  order, so the split survives redaction having shifted offsets. */
export function segments(answer: string, numbers: NumberCheck[]): Segment[] {
  const out: Segment[] = [];
  let cursor = 0;
  const ordered = [...numbers].sort((a, b) => a.start - b.start);
  ordered.forEach((n, index) => {
    const at = answer.indexOf(n.text, cursor);
    if (at < 0) return;
    if (at > cursor) out.push({ kind: "text", text: answer.slice(cursor, at) });
    out.push({ kind: "number", text: n.text, check: n, index });
    cursor = at + n.text.length;
  });
  if (cursor < answer.length) out.push({ kind: "text", text: answer.slice(cursor) });
  return out;
}

/** Where in a tool result a JSON path points, for showing the evidence. */
export function valueAt(obj: unknown, path: string): unknown {
  const parts = path.split(/[.[\]]/).filter(Boolean);
  let cur: unknown = obj;
  for (const p of parts) {
    if (cur === null || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[p];
  }
  return cur;
}
